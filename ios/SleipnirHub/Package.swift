// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "SleipnirHub",
    platforms: [
        // An iPhone 8 stops at iOS 16.7. Targeting v17 builds an app that
        // installs and then refuses to launch, which reads exactly like a
        // signing failure. Nothing in this app needs a v17 API.
        .iOS(.v16),
        .macOS(.v14),
    ],
    products: [
        // An xtool project should contain exactly one library product,
        // representing the main app.
        .library(
            name: "SleipnirHub",
            targets: ["SleipnirHub"]
        ),
    ],
    targets: [
        .target(
            name: "SleipnirHub"
        ),
    ]
)
