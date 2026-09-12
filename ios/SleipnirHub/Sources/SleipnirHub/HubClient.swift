import Foundation

struct HubStatus: Decodable {
    struct Run: Decodable {
        let id: String?
        let goal: String?
        let state: String?
    }

    struct Task: Decodable, Identifiable {
        let id: String
        let title: String?
        let status: String?
        let group: String?
    }

    struct Voice: Decodable {
        let phase: String
        let listening: Bool
    }

    let run: Run?
    let counts: [String: Int]
    let taskTotal: Int
    let tasks: [Task]
    let reviewCount: Int
    let voice: Voice
}

struct HubReview: Decodable, Identifiable {
    let id: String
    let title: String?
    let kind: String?
    let summary: String?
}

enum HubError: LocalizedError {
    case notPaired
    case unauthorised
    case http(Int)
    case message(String)

    var errorDescription: String? {
        switch self {
        case .notPaired: return "This phone is not paired with a desk yet."
        case .unauthorised: return "The desk rejected this token. Pair again."
        case let .http(code): return "The desk answered with HTTP \(code)."
        case let .message(text): return text
        }
    }
}

/// Every call to the desk, in one place.
///
/// There is no unauthenticated path: the token is attached in `request`, so a
/// new endpoint cannot be added that forgets it.
struct HubClient {
    var session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        // A desk that is asleep or off the network should fail in seconds, not
        // leave the phone showing a spinner for a minute.
        configuration.timeoutIntervalForRequest = 8
        return URLSession(configuration: configuration)
    }()

    private func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        guard let address = Pairing.address,
              let token = Pairing.token,
              let url = URL(string: address + path)
        else { throw HubError.notPaired }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw HubError.http(0) }
        if http.statusCode == 401 { throw HubError.unauthorised }
        guard (200..<300).contains(http.statusCode) else {
            // The hub answers errors as {"error": "..."}. Showing the desk's
            // own words beats "request failed" on a screen with no console.
            if let payload = try? JSONDecoder().decode([String: String].self, from: data),
               let detail = payload["error"] {
                throw HubError.message(detail)
            }
            throw HubError.http(http.statusCode)
        }
        return data
    }

    func status() async throws -> HubStatus {
        try JSONDecoder().decode(HubStatus.self, from: await request("/api/status"))
    }

    func reviews() async throws -> [HubReview] {
        try JSONDecoder().decode([HubReview].self, from: await request("/api/reviews"))
    }

    func screen() async throws -> Data {
        try await request("/api/screen")
    }

    func decide(_ id: String, decision: String) async throws {
        _ = try await request(
            "/api/reviews/" + id,
            method: "POST",
            body: try JSONEncoder().encode(["decision": decision])
        )
    }

    /// Ask the desk to switch the wake listener on or off.
    ///
    /// The desk *requests* this of its own host, so a success here means the
    /// ask arrived, not that the microphone changed. The next status poll is
    /// what confirms it, and that is what the toggle reflects.
    func setVoice(_ enabled: Bool) async throws {
        _ = try await request(
            "/api/voice",
            method: "POST",
            body: try JSONEncoder().encode(["enabled": enabled])
        )
    }
}
