// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "NXGameBuilder",
    platforms: [.macOS(.v15)],
    products: [.executable(name: "NXGameBuilder", targets: ["NXGameBuilder"])],
    targets: [.executableTarget(name: "NXGameBuilder")]
)
