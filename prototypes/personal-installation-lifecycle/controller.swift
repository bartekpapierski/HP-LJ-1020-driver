import Foundation
import ServiceManagement

private let plistName = "com.bartekpapierski.hplj1020.lifecycle.daemon.plist"
private let service = SMAppService.daemon(plistName: plistName)

private func statusName(_ status: SMAppService.Status) -> String {
    switch status {
    case .notRegistered:
        return "not-registered"
    case .enabled:
        return "enabled"
    case .requiresApproval:
        return "requires-approval"
    case .notFound:
        return "not-found"
    @unknown default:
        return "unknown-\(status.rawValue)"
    }
}

private func printStatus() {
    print("service_status=\(statusName(service.status))")
}

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: hplj1020-lifecycle status|register|unregister|open-settings\n", stderr)
    exit(2)
}

let command = CommandLine.arguments[1]

do {
    switch command {
    case "status":
        printStatus()
    case "register":
        if service.status == .notRegistered || service.status == .notFound {
            try service.register()
        }
        printStatus()
    case "unregister":
        if service.status == .enabled || service.status == .requiresApproval {
            try service.unregister()
        }
        printStatus()
    case "open-settings":
        SMAppService.openSystemSettingsLoginItems()
        printStatus()
    default:
        fputs("Unknown command. Use status, register, unregister, or open-settings.\n", stderr)
        exit(2)
    }
} catch {
    if command == "register" && service.status == .requiresApproval {
        print("service_registration=pending-approval")
        printStatus()
        exit(0)
    }

    let nsError = error as NSError
    fputs("service_error_domain=\(nsError.domain)\n", stderr)
    fputs("service_error_code=\(nsError.code)\n", stderr)
    fputs("service_error=\(nsError.localizedDescription)\n", stderr)
    printStatus()
    exit(1)
}
