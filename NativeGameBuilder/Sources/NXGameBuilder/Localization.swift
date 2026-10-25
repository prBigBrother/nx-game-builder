import Foundation

struct InterfaceLanguage {
    static func isRussian(_ selection: String) -> Bool {
        selection == "ru" || (selection == "system" && Locale.preferredLanguages.first?.hasPrefix("ru") == true)
    }
    static let russian: [String: String] = {
        guard let url = Bundle.main.url(forResource: "ru", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let catalog = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return catalog
    }()
    static func text(_ value: String, language: String) -> String {
        guard isRussian(language) else { return value }
        if let exact = russian[value] { return exact }
        if value.hasPrefix("Process exited with code ") {
            return value.replacingOccurrences(of: "Process exited with code ", with: "Процесс завершился с кодом ")
                .replacingOccurrences(of: ". See the log for details.", with: ". Подробности — в журнале.")
        }
        // Dynamic errors retain the original paths and numeric values.
        return russian.filter { $0.key.count > 10 }.sorted { $0.key.count > $1.key.count }
            .reduce(value) { $0.replacingOccurrences(of: $1.key, with: $1.value) }
    }
}
