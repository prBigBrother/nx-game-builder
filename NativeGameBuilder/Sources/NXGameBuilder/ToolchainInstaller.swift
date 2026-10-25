import AppKit
import Combine
import Darwin
import Foundation

final class ToolchainInstaller: ObservableObject {
    static let bundledResources = Bundle.main.resourceURL?.appendingPathComponent("Toolchain")
    static let bundledManifest: [String: Any]? = {
        guard let url = bundledResources?.appendingPathComponent("manifest.json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }()
    static var hasBundle: Bool { bundledManifest?["id"] as? String != nil }
    static var root: URL {
        let base = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/NX Game Builder/Tools")
        return bundledManifest?["id"] as? String == nil ? base : base.appendingPathComponent(bundledManifest!["id"] as! String)
    }
    static var python: URL {
        root.appendingPathComponent(hasBundle ? "python/bin/python3.13" : "venv/bin/python")
    }
    static var supportRoot: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/NX Game Builder")
    }
    @Published private(set) var running = false
    @Published private(set) var progress = 0.0
    @Published private(set) var stage = "Build tools are downloaded to your user Library."
    @Published private(set) var log = ""
    @Published private(set) var error: String?
    @Published private(set) var installed = false
    @Published private(set) var xcodeReady = false
    @Published private(set) var metalReady = false
    private var process: Process?
    private var cancelled = false
    private let dock = DockProgress()

    init() { refresh() }

    func refresh() {
        guard !running else { return }
        let marker = Self.root.appendingPathComponent("installed.json")
        installed = FileManager.default.fileExists(atPath: marker.path) &&
            FileManager.default.isExecutableFile(atPath: Self.python.path) &&
            FileManager.default.isExecutableFile(atPath: Self.root.appendingPathComponent("dotnet/dotnet").path)
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let dev = Self.output("/usr/bin/xcode-select", ["-p"])
            let xcode = dev.0 == 0 && dev.1.contains("Xcode") && dev.1.contains(".app/Contents/Developer")
            let metal = xcode && Self.output("/usr/bin/xcrun", ["-sdk", "macosx", "metal", "--version"]).0 == 0
            DispatchQueue.main.async { self?.xcodeReady = xcode; self?.metalReady = metal }
        }
    }

    private static func output(_ executable: String, _ arguments: [String]) -> (Int32, String) {
        let task = Process(), pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: executable); task.arguments = arguments
        task.standardOutput = pipe; task.standardError = pipe; task.standardInput = FileHandle.nullDevice
        do {
            try task.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            task.waitUntilExit()
            return (task.terminationStatus, String(decoding: data, as: UTF8.self))
        } catch { return (-1, error.localizedDescription) }
    }

    func start(metalOnly: Bool = false, completion: @escaping () -> Void) {
        let offline = Self.hasBundle && !metalOnly
        let name = offline ? "install_bundled_tools.sh" : "setup_tools.sh"
        guard !running, let script = Bundle.main.resourceURL?.appendingPathComponent("Backend/" + name) else { return }
        error = nil; log = ""; progress = 0; cancelled = false
        stage = metalOnly ? "Downloading Metal Toolchain" : "Preparing build tools"
        let task = Process(), pipe = Pipe()
        task.executableURL = URL(fileURLWithPath: "/bin/bash")
        task.arguments = offline ? [script.path, Self.root.path, Self.bundledResources!.path] : [script.path, Self.root.path, metalOnly ? "metal" : "install"]
        task.standardOutput = pipe; task.standardError = pipe; task.standardInput = FileHandle.nullDevice
        do {
            let logs = Self.supportRoot.appendingPathComponent("Logs")
            try FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
            let logURL = logs.appendingPathComponent("setup.log")
            try Data().write(to: logURL)
            let diskLog = try FileHandle(forWritingTo: logURL)
            try task.run(); process = task; running = true
            dock.update(running: true, fraction: 0)
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                defer { try? diskLog.close() }
                var buffer = Data()
                while true {
                    let data = pipe.fileHandleForReading.availableData
                    if data.isEmpty { break }
                    try? diskLog.write(contentsOf: data)
                    buffer.append(data)
                    while let end = buffer.firstIndex(where: { $0 == 10 || $0 == 13 }) {
                        let line = String(decoding: buffer[..<end], as: UTF8.self)
                        buffer.removeSubrange(...end)
                        DispatchQueue.main.async { self?.receive(line) }
                    }
                }
                if !buffer.isEmpty {
                    let line = String(decoding: buffer, as: UTF8.self)
                    DispatchQueue.main.async { self?.receive(line) }
                }
                task.waitUntilExit()
                let status = task.terminationStatus
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.running = false; self.process = nil
                    self.dock.update(running: false, fraction: self.progress)
                    if self.cancelled { self.stage = "Setup cancelled" }
                    else if status == 0 {
                        self.stage = metalOnly ? "Metal Toolchain installed" : "Build tools installed"
                        self.progress = 1
                        if !metalOnly { completion() }
                    } else {
                        self.stage = "Setup failed"
                        self.error = "See the setup log for details. Completed downloads are kept for retry."
                    }
                    self.refresh()
                }
            }
        } catch { self.error = error.localizedDescription }
    }

    private func receive(_ line: String) {
        guard !line.isEmpty else { return }
        if let data = line.data(using: .utf8),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           value["ev"] as? String == "setup_stage" {
            stage = value["name"] as? String ?? stage
            progress = max(progress, value["fraction"] as? Double ?? progress)
            dock.update(running: running, fraction: min(progress, 0.99))
        } else {
            log += line + "\n"
            if log.count > 80_000 { log = String(log.suffix(60_000)) }
        }
    }

    func cancel() {
        guard let process, process.isRunning else { return }
        cancelled = true
        if kill(-process.processIdentifier, SIGTERM) != 0 { process.terminate() }
    }
}
