import SwiftUI

/// One poller for the whole app.
///
/// `ObservableObject` rather than the `@Observable` macro: the macro is iOS 17
/// and this app has to run on an iPhone 8, which stops at 16.7.
@MainActor
final class HubStore: ObservableObject {
    @Published var status: HubStatus?
    @Published var reviews: [HubReview] = []
    @Published var error: String?
    @Published var paired = Pairing.isPaired

    private let client = HubClient()

    func refresh() async {
        guard paired else { return }
        do {
            async let status = client.status()
            async let reviews = client.reviews()
            self.status = try await status
            self.reviews = try await reviews
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    func decide(_ id: String, decision: String) async {
        do {
            try await client.decide(id, decision: decision)
            // Remove locally as well as refetching: on a slow link the row
            // would otherwise stay tappable and invite a second decision on a
            // proposal that no longer exists.
            reviews.removeAll { $0.id == id }
            await refresh()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func setVoice(_ enabled: Bool) async {
        do {
            try await client.setVoice(enabled)
            await refresh()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func screen() async -> UIImage? {
        guard let data = try? await client.screen() else { return nil }
        return UIImage(data: data)
    }

    func pair(address: String, token: String) {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        Pairing.address = trimmed.hasSuffix("/") ? String(trimmed.dropLast()) : trimmed
        Pairing.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        paired = Pairing.isPaired
        error = nil
    }

    func forget() {
        Pairing.forget()
        paired = false
        status = nil
        reviews = []
    }
}

public struct ContentView: View {
    @StateObject private var store = HubStore()

    public init() {}

    public var body: some View {
        Group {
            if store.paired {
                TabView {
                    StatusView(store: store)
                        .tabItem { Label("Status", systemImage: "gauge.medium") }
                    ReviewsView(store: store)
                        .tabItem {
                            Label("Review", systemImage: "checkmark.seal")
                        }
                        .badge(store.reviews.count)
                    ScreenView(store: store)
                        .tabItem { Label("Screen", systemImage: "display") }
                    PairingView(store: store)
                        .tabItem { Label("Desk", systemImage: "gearshape") }
                }
            } else {
                PairingView(store: store)
            }
        }
        .task {
            // A single poll loop for the app rather than one per tab: four
            // tabs each polling would quadruple the traffic and the battery
            // cost for the same information.
            while !Task.isCancelled {
                await store.refresh()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }
}

struct StatusView: View {
    @ObservedObject var store: HubStore

    var body: some View {
        NavigationStack {
            List {
                if let status = store.status {
                    Section("Voice") {
                        Toggle(
                            "Listening for the wake word",
                            isOn: Binding(
                                get: { status.voice.listening },
                                set: { value in Task { await store.setVoice(value) } }
                            )
                        )
                        LabeledContent("Phase", value: status.voice.phase)
                    }
                    Section("Run") {
                        LabeledContent("Goal", value: status.run?.goal ?? "No run open")
                        LabeledContent("Tasks", value: "\(status.taskTotal)")
                        ForEach(status.counts.sorted(by: { $0.key < $1.key }), id: \.key) { entry in
                            LabeledContent(entry.key.capitalized, value: "\(entry.value)")
                        }
                    }
                    if !status.tasks.isEmpty {
                        Section("Newest work") {
                            ForEach(status.tasks) { task in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(task.title ?? task.id)
                                    Text(task.status ?? "unknown")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                } else {
                    Text(store.error ?? "Reaching the desk…")
                        .foregroundStyle(.secondary)
                }
            }
            .refreshable { await store.refresh() }
            .navigationTitle("Sleipnir")
        }
    }
}

struct ReviewsView: View {
    @ObservedObject var store: HubStore

    var body: some View {
        NavigationStack {
            List {
                if store.reviews.isEmpty {
                    Text("Nothing is waiting on you.").foregroundStyle(.secondary)
                }
                ForEach(store.reviews) { review in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(review.title ?? review.id).font(.headline)
                        if let summary = review.summary, !summary.isEmpty {
                            Text(summary).font(.subheadline).foregroundStyle(.secondary)
                        }
                        HStack {
                            Button("Approve") {
                                Task { await store.decide(review.id, decision: "approve") }
                            }
                            .buttonStyle(.borderedProminent)
                            Button("Deny", role: .destructive) {
                                Task { await store.decide(review.id, decision: "reject") }
                            }
                            .buttonStyle(.bordered)
                        }
                        // Without this the whole row is one tap target and
                        // either button fires whichever the row decided to
                        // own, which is the wrong default for a destructive
                        // action reached from a pocket.
                        .buttonStyle(.automatic)
                    }
                    .padding(.vertical, 4)
                }
            }
            .refreshable { await store.refresh() }
            .navigationTitle("Review")
        }
    }
}

struct ScreenView: View {
    @ObservedObject var store: HubStore
    @State private var image: UIImage?
    @State private var loading = false

    var body: some View {
        NavigationStack {
            Group {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .accessibilityLabel("The desk's current screen")
                } else {
                    Text(loading ? "Capturing…" : "Pull down to see the desk's screen.")
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .refreshable { await load() }
            .navigationTitle("Screen")
            .toolbar {
                Button("Refresh") { Task { await load() } }
            }
        }
    }

    private func load() async {
        // Fetched on demand, never polled: each call wakes the compositor and
        // sends a photograph of the operator's desk across the network.
        loading = true
        image = await store.screen()
        loading = false
    }
}

struct PairingView: View {
    @ObservedObject var store: HubStore
    @State private var address = Pairing.address ?? "http://"
    @State private var token = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.1.20:8765", text: $address)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    SecureField("Pairing token", text: $token)
                } header: {
                    Text("Desk")
                } footer: {
                    Text("Open Sleipnir on your computer, turn on the phone hub in Settings, and copy the address and token it shows.")
                }
                Button("Pair") {
                    store.pair(address: address, token: token)
                    token = ""
                }
                .disabled(address.count < 8 || token.isEmpty)
                if store.paired {
                    Button("Forget this desk", role: .destructive) { store.forget() }
                }
                if let error = store.error {
                    Text(error).foregroundStyle(.red)
                }
            }
            .navigationTitle("Desk")
        }
    }
}
