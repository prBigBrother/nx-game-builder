import AppKit
import Combine
import Foundation
import Darwin

struct BuildConfiguration: Codable, Equatable {
    var repository = ""
    var python = ""
    var dotnet = ""
    var keys = ""
    var work = ""
    var destination = "/Applications"
    var base = ""
    var update = ""
    var dlc: [String] = []
    var language = "en-US"
    var reuseExisting = true
    var importSaves = true
    var experimental: Bool? = false
    var toolsBin: String?
}

final class BuilderModel: ObservableObject {
    @Published var config = BuildConfiguration()
    @Published var running = false
    @Published var cancelling = false
    @Published var stage = "Select a base game"
    @Published var detail = ""
    @Published var fraction: Double?
    @Published var log = ""
    @Published var installedApp: URL?
    @Published var errorMessage: String?
    @Published var logDirectory: URL?
    @Published var checked = false
    @Published var surveyReport: URL?
    @Published var interfaceLanguage = UserDefaults.standard.string(forKey: "interfaceLanguage") ?? "system" {
        didSet { defaults.set(interfaceLanguage, forKey: "interfaceLanguage") }
    }
    @Published private(set) var overallFraction = 0.0
    private var buildProgress = BuildProgress()
    private let dockProgress = DockProgress()
    func text(_ value: String) -> String { InterfaceLanguage.text(value, language: interfaceLanguage) }
    private var process: Process?
    private var configURL: URL?
    private var completed = false
    private var inspecting = false
    private let defaults = UserDefaults.standard

    init() {
        if let data = defaults.data(forKey: "configuration"), let saved = try? JSONDecoder().decode(BuildConfiguration.self, from: data) {
            config = saved
        } else if let url = Bundle.main.url(forResource: "defaults", withExtension: "json"),
                  let data = try? Data(contentsOf: url), let saved = try? JSONDecoder().decode(BuildConfiguration.self, from: data) {
            config = saved
        }
    }

    var hasSelectedTools: Bool {
        FileManager.default.isExecutableFile(atPath: config.python) &&
        FileManager.default.isExecutableFile(atPath: URL(fileURLWithPath: config.dotnet).appendingPathComponent("dotnet").path) &&
        FileManager.default.fileExists(atPath: URL(fileURLWithPath: config.repository).appendingPathComponent("scripts/build_ipa_from_nsp.py").path)
    }

    func useManagedTools() {
        let root = ToolchainInstaller.root
        config.repository = root.appendingPathComponent("nxnative").path
        config.python = ToolchainInstaller.python.path
        config.dotnet = root.appendingPathComponent("dotnet").path
        config.toolsBin = root.appendingPathComponent("bin").path
        if config.work.isEmpty || !FileManager.default.fileExists(atPath: config.work) {
            config.work = ToolchainInstaller.supportRoot.appendingPathComponent("Builds").path
        }
        persist()
    }

    func persist() {
        if let data = try? JSONEncoder().encode(config) { defaults.set(data, forKey: "configuration") }
    }

    var canBuild: Bool {
        !running && !config.base.isEmpty && !config.keys.isEmpty && !config.repository.isEmpty && !config.python.isEmpty
    }

    func append(_ text: String) {
        log += text + "\n"
        if log.count > 160_000 { log = String(log.suffix(120_000)) }
    }

    func start(inspect: Bool = false) {
        guard !running else { return }
        persist()
        buildProgress.reset()
        overallFraction = 0
        errorMessage = nil
        surveyReport = nil
        installedApp = nil
        completed = false
        cancelling = false
        inspecting = inspect
        checked = false
        log = ""
        detail = ""
        fraction = nil
        stage = inspect ? "Checking environment…" : "Preparing build…"
        guard let backend = Bundle.main.resourceURL?.appendingPathComponent("Backend/build_game.py") else { return }
        do {
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("nx-builder-\(UUID().uuidString).json")
            let data = try JSONEncoder().encode(config)
            try data.write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
            configURL = file
            let task = Process()
            task.executableURL = URL(fileURLWithPath: (config.python as NSString).expandingTildeInPath)
            task.arguments = ["-u", backend.path, "--config", file.path] + (inspect ? ["--inspect"] : [])
            var environment = ProcessInfo.processInfo.environment
            environment["PYTHONUNBUFFERED"] = "1"
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            task.environment = environment
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe
            task.standardInput = FileHandle.nullDevice
            try task.run()
            process = task
            running = true
            updateDock()
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                var buffer = Data()
                let handle = pipe.fileHandleForReading
                while true {
                    let chunk = handle.availableData
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    while let end = buffer.firstIndex(of: 10) {
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
                DispatchQueue.main.async { self?.finished(status) }
            }
        } catch {
            if let file = configURL { try? FileManager.default.removeItem(at: file) }
            configURL = nil
            errorMessage = error.localizedDescription
            append(error.localizedDescription)
            stage = "Could not start build"
        }
    }

    func cancel() {
        guard let task = process, task.isRunning, !cancelling else { return }
        cancelling = true
        stage = "Cancelling…"
        // Python creates its own process group; stop compiler/capture children too.
        if kill(-task.processIdentifier, SIGTERM) != 0 { task.terminate() }
    }

    func shutdown() {
        guard let task = process, task.isRunning else { return }
        if kill(-task.processIdentifier, SIGTERM) != 0 { task.terminate() }
    }

    private func updateDock() {
        overallFraction = buildProgress.value
        dockProgress.update(running: running, fraction: overallFraction)
    }

    private func receive(_ line: String) {
        defer { updateDock() }
        guard let data = line.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let kind = value["ev"] as? String else {
            if !line.isEmpty { append(line) }
            return
        }
        switch kind {
        case "stage":
            stage = Self.translate(value["name"] as? String ?? "Build")
            buildProgress.stage(value["name"] as? String ?? stage)
            detail = value["step"] as? String ?? ""
            fraction = nil
            append(stage)
        case "step", "progress":
            if let step = value["step"] as? String { detail = Self.translate(step) }
            if let total = value["total"] as? Double, total > 0, let done = value["done"] as? Double {
                fraction = min(1, max(0, done / total))
                if value["unit"] as? String == "B" {
                    detail = ByteCountFormatter.string(fromByteCount: Int64(done), countStyle: .file) + " / " + ByteCountFormatter.string(fromByteCount: Int64(total), countStyle: .file)
                } else {
                    detail += " · \(Int(done)) / \(Int(total))"
                }
            } else { fraction = nil }
            buildProgress.update(fraction)
            if let note = value["note"] as? String, !note.isEmpty { detail += " · " + note }
        case "say":
            if let text = (value["text"] ?? value["msg"]) as? String { append(text) }
        case "stage_end":
            if value["ok"] as? Bool == true { buildProgress.update(1) }
            if let note = (value["summary"] ?? value["note"]) as? String, !note.isEmpty { append(note) }
        case "identified":
            if let title = value["title"] as? String { append("Game: " + title) }
            if let logs = value["logs"] as? String { logDirectory = URL(fileURLWithPath: logs) }
        case "survey":
            if let path = value["report"] as? String { surveyReport = URL(fileURLWithPath: path) }
            append("Provisional profile created. Game compatibility is unverified.")
        case "complete":
            buildProgress.complete()
            if let app = value["app"] as? String {
                installedApp = URL(fileURLWithPath: app)
                completed = true
                append("Installed: " + app)
            }
        case "checked":
            checked = true
            append(value["message"] as? String ?? "Checks passed")
        case "error":
            errorMessage = value["message"] as? String ?? "Build error"
            append(errorMessage!)
        case "cancelled":
            cancelling = true
            append(value["message"] as? String ?? "Build cancelled")
        default: break
        }
    }

    private func finished(_ status: Int32) {
        defer { updateDock() }
        running = false
        process = nil
        if let file = configURL { try? FileManager.default.removeItem(at: file) }
        configURL = nil
        if cancelling {
            stage = "Build cancelled"
            fraction = nil
        } else if status == 0 && (completed || (inspecting && checked)) {
            stage = inspecting ? "Environment ready" : "App installed"
            fraction = 1
            buildProgress.complete()
        } else {
            stage = "Build failed"
            fraction = nil
            if errorMessage == nil { errorMessage = "Process exited with code \(status). See the log for details." }
        }
        cancelling = false
    }

    static func translate(_ text: String) -> String {
        let names = ["rewrite": "Rewriting game code", "shader split": "Extracting shaders", "GLSLC capture": "Capturing runtime shaders", "extract DLC": "Extracting DLC", "translating": "Translating shaders", "compiling": "Compiling", "cache check": "Checking cache", "checking the inputs": "Checking inputs", "finishing": "Finishing stage"]
        if let name = names[text] { return name }
        if text.hasPrefix("extract v") { return text.replacingOccurrences(of: "extract ", with: "Extracting version ") }
        return text
    }
}
