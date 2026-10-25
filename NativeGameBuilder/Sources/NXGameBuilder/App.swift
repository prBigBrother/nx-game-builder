import AppKit
import SwiftUI
import UniformTypeIdentifiers

final class AppDelegate: NSObject, NSApplicationDelegate {
    var model: BuilderModel?
    var installer: ToolchainInstaller?
    func applicationWillTerminate(_ notification: Notification) { model?.shutdown(); installer?.cancel() }
}

@main
struct NXGameBuilderApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = BuilderModel()
    @StateObject private var installer = ToolchainInstaller()
    var body: some Scene {
        WindowGroup("NX Game Builder") {
            BuilderView(model: model, installer: installer)
                .onAppear { delegate.model = model; delegate.installer = installer }
                .frame(minWidth: 880, minHeight: 680)
        }
        .defaultSize(width: 1020, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}

struct BuilderView: View {
    @ObservedObject var model: BuilderModel
    @ObservedObject var installer: ToolchainInstaller
    @State private var tab: Int? = 0
    @State private var showSetup = false
    var pageTitle: String { model.text(tab == 1 ? "Settings" : tab == 2 ? "Log" : "Build") }
    var busy: Bool { model.running || installer.running }

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                List(selection: $tab) {
                    Label(model.text("Build"), systemImage: "shippingbox").tag(0)
                    Label(model.text("Settings"), systemImage: "gearshape").tag(1)
                    Label(model.text("Log"), systemImage: "text.alignleft").tag(2)
                }.listStyle(.sidebar)
                HStack(spacing: 8) {
                    Image(nsImage: NSApplication.shared.applicationIconImage)
                        .resizable().frame(width: 28, height: 28)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("NX Game Builder").font(.caption.weight(.semibold))
                        Text(model.text("Native game builds")).font(.caption2).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 0)
                }.padding(16)
            }.navigationSplitViewColumnWidth(min: 180, ideal: 205, max: 240)
        } detail: {
            VStack(spacing: 0) {
                Group {
                    switch tab {
                    case 1: settingsForm
                    case 2: logView
                    default: buildForm
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
                statusBar
            }
            .navigationTitle(pageTitle)
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    if tab == 1 {
                        Button { installer.refresh() } label: {
                            Label(model.text("Refresh"), systemImage: "arrow.clockwise")
                        }.disabled(busy).help(model.text("Refresh"))
                    }
                    if model.running {
                        Button(model.text("Cancel"), role: .cancel) { model.cancel() }.disabled(model.cancelling)
                    } else if installer.running {
                        Button(model.text("Cancel"), role: .cancel) { installer.cancel() }
                    } else {
                        Button(model.text("Build & Install")) { tab = 0; model.start() }
                            .buttonStyle(.borderedProminent).disabled(!model.canBuild)
                    }
                }
            }
        }
        .onChange(of: model.config) { _, _ in model.persist() }
        .onAppear {
            if !model.hasSelectedTools {
                if installer.installed { model.useManagedTools() }
                else { showSetup = true }
            }
        }
        .sheet(isPresented: $showSetup) {
            VStack(alignment: .leading, spacing: 18) {
                Label(model.text("Welcome to NX Game Builder"), systemImage: "shippingbox")
                    .font(.title2.weight(.semibold))
                Text(model.text("Set up the build tools once, then turn your game images into standalone Mac apps."))
                    .foregroundStyle(.secondary)
                toolDownloadSection
                HStack {
                    Button(model.text("Set up later")) { showSetup = false }.disabled(installer.running)
                    Spacer()
                    if model.hasSelectedTools {
                        Button(model.text("Continue")) { showSetup = false }
                            .buttonStyle(.borderedProminent)
                    }
                }
            }.padding(24).frame(width: 620)
                .interactiveDismissDisabled(installer.running)
        }
    }

    var statusBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()
            HStack {
                Label(model.text(model.running || model.errorMessage != nil || model.installedApp != nil ? model.stage : (model.canBuild ? "Ready to build" : "Select a base game")),
                      systemImage: model.errorMessage != nil ? "exclamationmark.triangle" : (model.installedApp != nil ? "checkmark.circle" : "shippingbox"))
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if let report = model.surveyReport {
                    Button(model.text("Game report")) { NSWorkspace.shared.open(report) }
                }
                if let app = model.installedApp {
                    Button(model.text("Open game")) { NSWorkspace.shared.open(app) }
                    Button(model.text("Show in Finder")) { NSWorkspace.shared.activateFileViewerSelecting([app]) }
                }
            }
            if model.running {
                HStack {
                    Text(model.text("Overall progress (estimated)"))
                    Spacer()
                    Text(model.overallFraction, format: .percent.precision(.fractionLength(0))).monospacedDigit()
                }.font(.caption).foregroundStyle(.secondary)
                ProgressView(value: model.overallFraction)
                if let value = model.fraction {
                    ProgressView(value: value).help(model.text("Current stage"))
                } else { ProgressView().progressViewStyle(.linear) }
                if !model.detail.isEmpty { Text(model.text(model.detail)).font(.caption).foregroundStyle(.secondary).lineLimit(2) }
            }
            if let error = model.errorMessage {
                Label(model.text(error), systemImage: "exclamationmark.triangle")
                    .font(.callout).foregroundStyle(.red).textSelection(.enabled)
            }
        }.padding(.horizontal, 16).padding(.bottom, 10).background(.bar)
    }

    var toolDownloadSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(model.text("Apple developer tools")).font(.callout.weight(.medium))
                Spacer()
                Button(model.text("Refresh")) { installer.refresh() }.disabled(busy)
            }
            LabeledContent("Xcode") {
                if installer.xcodeReady { Label(model.text("Installed"), systemImage: "checkmark.circle").foregroundStyle(.secondary) }
                else { Link(model.text("Get Xcode"), destination: URL(string: "https://apps.apple.com/app/xcode/id497799835")!) }
            }
            LabeledContent("Metal Toolchain") {
                if installer.metalReady { Label(model.text("Installed"), systemImage: "checkmark.circle").foregroundStyle(.secondary) }
                else {
                    Button(model.text("Download Metal Toolchain")) { installer.start(metalOnly: true) {} }
                        .disabled(busy || !installer.xcodeReady)
                }
            }
            if !installer.xcodeReady {
                Text(model.text("Install and open Xcode, complete its setup, then select it in Xcode Settings → Locations → Command Line Tools."))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            Text(model.text("Python, .NET SDK 10, nxnative, SPIRV-Cross, GLSL compiler, and Zstandard."))
                .font(.callout)
            Text(model.text(ToolchainInstaller.hasBundle ? "Build tools are included in this app. Install them locally without downloads. Xcode, Metal Toolchain, and game keys are provided separately." : "Installed in your user Library. No Homebrew or administrator access is required. Game keys are provided separately."))
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Button(model.text(ToolchainInstaller.hasBundle ? (installer.installed ? "Reinstall bundled tools" : "Install bundled tools") : (installer.installed ? "Repair build tools" : "Download build tools"))) {
                    installer.start { model.useManagedTools() }
                }.disabled(busy || (!ToolchainInstaller.hasBundle && (!installer.xcodeReady || !installer.metalReady)))
                if installer.installed {
                    Button(model.text(ToolchainInstaller.hasBundle ? "Use bundled tools" : "Use downloaded tools")) { model.useManagedTools() }.disabled(busy)
                }
                Spacer()
                if installer.running { Button(model.text("Cancel")) { installer.cancel() } }
            }
            if installer.running || installer.progress > 0 || installer.error != nil {
                Text(model.text(installer.stage)).font(.callout)
                if installer.running { ProgressView(value: installer.progress) }
                if let error = installer.error { Text(model.text(error)).foregroundStyle(.red).font(.caption) }
            }
            if !installer.log.isEmpty {
                DisclosureGroup(model.text("Setup log")) {
                    ScrollView {
                        Text(installer.log).font(.system(.caption, design: .monospaced))
                            .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                    }.frame(height: 150)
                }
            }
        }
    }

    var buildForm: some View {
        Form {
            Section(model.text("Game")) {
                pathRow(model.text("Base game"), path: $model.config.base, types: ["nsp", "xci", "nsz", "xcz"])
                pathRow(model.text("Update"), path: $model.config.update, types: ["nsp", "nsz"], optional: true)
            }.disabled(busy)
            Section {
                HStack {
                    Label(model.text("Add-ons"), systemImage: "puzzlepiece.extension")
                    Text("\(model.config.dlc.count)").foregroundStyle(.secondary).monospacedDigit()
                    Spacer()
                    Button(model.text("Add…")) { addDLC() }
                    if !model.config.dlc.isEmpty {
                        Button(model.text("Clear")) { model.config.dlc = []; model.persist() }
                    }
                }
                if model.config.dlc.isEmpty {
                    Text(model.text("Optionally add DLC for this game."))
                        .font(.callout).foregroundStyle(.secondary)
                } else {
                    ScrollView {
                        VStack(spacing: 0) {
                            ForEach(model.config.dlc, id: \.self) { path in
                                HStack(spacing: 10) {
                                    Image(systemName: "doc.zipper").foregroundStyle(.secondary)
                                    Text(URL(fileURLWithPath: path).lastPathComponent)
                                        .font(.callout).lineLimit(1).truncationMode(.middle).help(path)
                                    Spacer(minLength: 8)
                                    Button { model.config.dlc.removeAll { $0 == path }; model.persist() } label: {
                                        Image(systemName: "minus.circle")
                                    }.buttonStyle(.borderless).help(model.text("Remove DLC"))
                                }.padding(.vertical, 7)
                            }
                        }
                    }.frame(height: min(170, CGFloat(model.config.dlc.count * 34)))
                }
            }.disabled(busy)
            Section(model.text("Image access")) {
                pathRow(model.text("prod.keys file"), path: $model.config.keys, types: ["keys"])
            }.disabled(busy)
            Section(model.text("Compatibility")) {
                Toggle(model.text("Experimental games"), isOn: Binding(
                    get: { model.config.experimental ?? false },
                    set: { model.config.experimental = $0 }
                ))
                Text(model.text("Analyze games without a registered profile, create a provisional profile, and attempt a build. Further compatibility fixes may be needed. The report is kept even if the build fails."))
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(busy)
            Section(model.text("Output app")) {
                pathRow(model.text("Install folder"), path: $model.config.destination, directory: true)
                Picker(model.text("Game language"), selection: $model.config.language) {
                    Text("English").tag("en-US")
                    Text("Русский").tag("ru")
                    Text("日本語").tag("ja")
                    Text("Deutsch").tag("de")
                    Text("Français").tag("fr")
                    Text("Español").tag("es")
                    Text("Italiano").tag("it")
                    Text("简体中文").tag("zh-Hans")
                }
                Text(model.text("The selected game must support this language.")).font(.caption).foregroundStyle(.secondary)
                Label(model.text("Game resources, DLC, and Metal shaders are bundled inside the app."), systemImage: "shippingbox")
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(busy)
        }.formStyle(.grouped)
    }

    var settingsForm: some View {
        Form {
            Section(model.text("Appearance")) {
                Picker(model.text("Interface language"), selection: $model.interfaceLanguage) {
                    Text(model.text("System")).tag("system")
                    Text("English").tag("en")
                    Text("Русский").tag("ru")
                }
            }
            Section(model.text("Toolchain")) {
                toolDownloadSection
                Button(model.text("Setup assistant…")) { showSetup = true }.disabled(busy)
            }
            Section(model.text("Build tools")) {
                pathRow("nxnative", path: $model.config.repository, directory: true).disabled(busy)
                pathRow("Python", path: $model.config.python).disabled(busy)
                pathRow(model.text(".NET SDK folder"), path: $model.config.dotnet, directory: true).disabled(busy)
                HStack {
                    Button(model.text("Check environment")) { model.start(inspect: true) }.disabled(busy)
                    if model.checked { Label(model.text("Ready"), systemImage: "checkmark.circle") }
                }
                Text(model.text("Building requires Xcode with Metal, .NET SDK 10, spirv-cross, and Python with nxnative dependencies. Built games run independently."))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section(model.text("About")) {
                LabeledContent("NX Game Builder", value: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "")
                Link(model.text("Powered by nxnative"), destination: URL(string: "https://github.com/seedds/nxnative")!)
                Button(model.text("Third-party licenses")) {
                    if let url = Bundle.main.resourceURL?.appendingPathComponent("Licenses") { NSWorkspace.shared.open(url) }
                }
                Link(model.text("Releases and source code"), destination: URL(string: "https://github.com/prBigBrother/nx-game-builder")!)
            }
            Section(model.text("Working files")) {
                pathRow(model.text("Build folder"), path: $model.config.work, directory: true)
                Toggle(model.text("Reuse an existing build next to the image"), isOn: $model.config.reuseExisting)
                Toggle(model.text("Import existing saves on first install"), isOn: $model.config.importSaves)
                Text(model.text("Completed steps and caches are kept for later builds. Registered nxnative profiles define supported games and versions."))
                    .font(.caption).foregroundStyle(.secondary)
            }.disabled(busy)
        }.formStyle(.grouped)
    }

    var logView: some View {
        VStack(alignment: .leading) {
            HStack {
                Button(model.text("Copy log")) {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(model.log, forType: .string)
                }.disabled(model.log.isEmpty)
                if let directory = model.logDirectory {
                    Button(model.text("Log folder")) { NSWorkspace.shared.open(directory) }
                }
                Spacer()
            }
            ScrollView {
                Text(model.log.isEmpty ? model.text("Build activity and errors will appear here.") : model.log)
                    .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(8)
            }.border(.separator)
        }.padding()
    }

    func pathRow(_ title: String, path: Binding<String>, types: [String] = [], directory: Bool = false, optional: Bool = false) -> some View {
        HStack(spacing: 12) {
            Image(systemName: directory ? "folder" : (types.contains("keys") ? "key" : "doc.zipper"))
                .font(.title3).foregroundStyle(.secondary).frame(width: 24)
            VStack(alignment: .leading, spacing: 4) {
                Text(model.text(title)).font(.callout.weight(.medium))
                Text(path.wrappedValue.isEmpty ? (optional ? model.text("Optional") : model.text("Select a file or folder")) : URL(fileURLWithPath: path.wrappedValue).lastPathComponent)
                    .font(.callout).foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.middle).help(path.wrappedValue)
            }
            Spacer(minLength: 8)
                if optional && !path.wrappedValue.isEmpty {
                    Button(model.text("Remove")) { path.wrappedValue = ""; model.persist() }
                }
                Button(model.text("Choose…")) {
                    let panel = NSOpenPanel()
                    panel.title = model.text(title)
                    panel.canChooseDirectories = directory
                    panel.canChooseFiles = !directory
                    panel.canCreateDirectories = directory
                    panel.showsHiddenFiles = true
                    if !types.isEmpty { panel.allowedContentTypes = types.compactMap { UTType(filenameExtension: $0) } }
                    if !path.wrappedValue.isEmpty {
                        let url = URL(fileURLWithPath: path.wrappedValue)
                        panel.directoryURL = directory ? url : url.deletingLastPathComponent()
                    }
                    if panel.runModal() == .OK, let url = panel.url { path.wrappedValue = url.path; model.persist() }
                }
        }
        .padding(.vertical, 5)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("path-\(title)")
    }

    func addDLC() {
        let panel = NSOpenPanel()
        panel.title = model.text("Select DLC")
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = ["nsp", "nsz"].compactMap { UTType(filenameExtension: $0) }
        if panel.runModal() == .OK {
            for url in panel.urls where !model.config.dlc.contains(url.path) { model.config.dlc.append(url.path) }
            model.persist()
        }
    }
}
