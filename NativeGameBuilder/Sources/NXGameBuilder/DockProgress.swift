import AppKit
import SwiftUI

final class DockProgress {
    private var visible = false
    func update(running: Bool, fraction: Double) {
        let tile = NSApplication.shared.dockTile
        if running {
            let icon = NSApplication.shared.applicationIconImage ?? NSImage()
            tile.contentView = NSHostingView(rootView:
                VStack(spacing: 0) {
                    Image(nsImage: icon).resizable().scaledToFit()
                    ProgressView(value: fraction).progressViewStyle(.linear)
                        .tint(.accentColor).padding(.horizontal, 10).padding(.bottom, 8)
                }.frame(width: tile.size.width, height: tile.size.height)
            )
            visible = true
            tile.display()
        } else if visible {
            tile.contentView = nil
            tile.display()
            visible = false
        }
    }
}
