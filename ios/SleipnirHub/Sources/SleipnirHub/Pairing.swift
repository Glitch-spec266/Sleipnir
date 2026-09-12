import Foundation

/// Where the phone remembers the desk it belongs to.
///
/// The address is ordinary preference data and lives in `UserDefaults`. The
/// token is a credential and lives in the keychain: `UserDefaults` is inside
/// the app sandbox, but it is also written verbatim into an unencrypted
/// iTunes/Finder backup, and a bearer token that unlocks a live view of the
/// operator's screen does not belong in one.
enum Pairing {
    private static let addressKey = "sleipnir.hub.address"
    private static let account = "sleipnir.hub.token"

    static var address: String? {
        get { UserDefaults.standard.string(forKey: addressKey) }
        set { UserDefaults.standard.set(newValue, forKey: addressKey) }
    }

    static var token: String? {
        get { readToken() }
        set {
            if let value = newValue, !value.isEmpty {
                writeToken(value)
            } else {
                deleteToken()
            }
        }
    }

    static var isPaired: Bool {
        guard let address, let url = URL(string: address),
              let host = url.host, !host.isEmpty,
              url.scheme == "http",
              let token, !token.isEmpty
        else { return false }
        // The desktop hub is intentionally LAN-only. Refusing arbitrary web
        // addresses keeps the local-network transport exception from turning
        // this small client into a bearer-token sender for remote hosts.
        return host == "localhost" || host.hasSuffix(".local") || isPrivateIPv4(host)
    }

    private static func isPrivateIPv4(_ host: String) -> Bool {
        let octets = host.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else {
            return false
        }
        return octets[0] == 10
            || (octets[0] == 172 && (16...31).contains(octets[1]))
            || (octets[0] == 192 && octets[1] == 168)
            || octets[0] == 127
    }

    static func forget() {
        address = nil
        token = nil
    }

    // MARK: - Keychain

    private static func query() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "dev.sleipnir.hub",
            kSecAttrAccount as String: account,
        ]
    }

    private static func readToken() -> String? {
        var lookup = query()
        lookup[kSecReturnData as String] = true
        lookup[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(lookup as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data
        else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func writeToken(_ value: String) {
        deleteToken()
        var entry = query()
        entry[kSecValueData as String] = Data(value.utf8)
        // The hub is only reachable while the phone is unlocked and on the
        // same network, and this device only: a token that syncs to iCloud
        // would follow the operator onto hardware that was never paired.
        entry[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        SecItemAdd(entry as CFDictionary, nil)
    }

    private static func deleteToken() {
        SecItemDelete(query() as CFDictionary)
    }
}
