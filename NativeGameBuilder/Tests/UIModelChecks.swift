import AppKit
import Foundation

@main
struct UIModelChecks {
    static func main() {
        var progress = BuildProgress()
        progress.stage("survey: code modules")
        progress.update(0.5)
        let survey = progress.value
        progress.stage("survey: build nx_extract")
        assert(progress.value >= survey, "Survey substeps cannot move backwards")
        progress.stage("rewrite")
        progress.update(1)
        let rewrite = progress.value
        progress.stage("Building Metal shaders")
        progress.update(0.5)
        assert(progress.value > rewrite && progress.value < 0.81)
        let shaders = progress.value
        progress.update(0.1)
        assert(progress.value == shaders, "A compiler substep cannot move backwards")
        progress.stage("Bundling game resources")
        progress.update(1)
        assert(progress.value == 0.95)
        progress.stage("Installing app")
        progress.update(1)
        assert(progress.value < 1, "Only successful completion may show 100 percent")
        progress.complete()
        assert(progress.value == 1)
        progress.reset()
        assert(progress.value == 0)
        assert(InterfaceLanguage.text("Build", language: "en") == "Build")
        assert(InterfaceLanguage.isRussian("ru"))
        assert(!InterfaceLanguage.isRussian("en"))
        let dock = DockProgress()
        dock.update(running: true, fraction: 0.56)
        assert(NSApplication.shared.dockTile.contentView != nil)
        dock.update(running: false, fraction: 0.56)
        assert(NSApplication.shared.dockTile.contentView == nil)
        print("Progress monotonicity, completion, reset, language selection and Dock lifecycle passed")
    }
}
