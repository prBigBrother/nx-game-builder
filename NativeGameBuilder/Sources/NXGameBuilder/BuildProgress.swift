import Foundation

/// Phase-weighted estimate, independent of the upstream stage count (which can reset).
struct BuildProgress {
    private(set) var value = 0.0
    private var range = 0.0...0.02

    mutating func reset() { value = 0; range = 0...0.02 }
    mutating func stage(_ name: String) {
        let name = name.lowercased()
        switch name {
        case let n where n.contains("installing app"): range = 0.98...0.99
        case let n where n.contains("existing saves"): range = 0.97...0.98
        case let n where n.contains("code signing"): range = 0.95...0.97
        case let n where n.contains("bundling game"): range = 0.86...0.95
        case let n where n.contains("macos executable") || n.contains("preparing fonts"): range = 0.83...0.86
        case let n where n.contains("shader tables"): range = 0.81...0.83
        case let n where n.contains("metal shaders"): range = 0.46...0.81
        case let n where n.contains("shader split"): range = 0.42...0.46
        case let n where n.contains("capture") || n.contains("decode") || n.contains("shader tools"): range = 0.39...0.42
        case let n where n.contains("heap check") || n.contains("refining provisional"): range = 0.36...0.39
        case let n where n.contains("rewrit"): range = 0.31...0.36
        case let n where n.hasPrefix("extract "): range = 0.14...0.31
        case let n where n.contains("extraction tool"): range = 0.12...0.14
        case let n where n.hasPrefix("survey:"): range = 0.04...0.12
        default: break
        }
        update(nil)
    }
    mutating func update(_ fraction: Double?) {
        let fraction = min(1, max(0, fraction ?? 0))
        value = max(value, min(0.99, range.lowerBound + (range.upperBound - range.lowerBound) * fraction))
    }
    mutating func complete() { value = 1 }
}
