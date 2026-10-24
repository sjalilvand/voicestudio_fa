import Foundation

public enum NativeComputeMode: Sendable, Equatable { case automatic, cpuOnly }

/// A job's CPU choice follows its native worker without changing another task or process environment.
public enum NativeExecutionContext {
    @TaskLocal public static var compute: NativeComputeMode = .automatic
    static func detached<T: Sendable>(_ operation: @escaping @Sendable () async throws -> T) -> Task<T, any Error> {
        let snapshot = compute
        return Task.detached(priority: .userInitiated) {
            try await $compute.withValue(snapshot,operation: operation)
        }
    }
}

public enum PhoneBackgroundGrant: Sendable, Equatable { case none, finiteCPU, continuedCPU, continuedGPU }
public enum PhoneBackgroundDecision: Sendable, Equatable { case continueCurrent, checkpointAndPause, restartOnCPU }

/// A submitted request is not a grant. GPU work needs an attached GPU task; CPU work can also use UIKit's finite grace period.
public enum PhoneBackgroundPolicy {
    public static func decision(requiresGPU: Bool,compute: NativeComputeMode,grant: PhoneBackgroundGrant,
                                supportsGPU: Bool,allowCPUFallback: Bool,cpuAvailable: Bool) -> PhoneBackgroundDecision {
        if requiresGPU && compute == .automatic {
            if supportsGPU && grant == .continuedGPU { return .continueCurrent }
            if allowCPUFallback && cpuAvailable && grant != .none { return .restartOnCPU }
            return .checkpointAndPause
        }
        return grant == .none ? .checkpointAndPause : .continueCurrent
    }
}

/// The old operation must return (including native cleanup) before a replacement can start.
/// Explicit cancellation or expiration always overrides an outstanding CPU handoff.
public struct PhoneJobRestartGate: Sendable {
    public enum Stop: Sendable { case cpuHandoff, user, expired, power }
    private var stopping: Stop?
    public init() {}
    public mutating func request(_ reason: Stop) {
        if stopping == nil || reason != .cpuHandoff { stopping = reason }
    }
    public mutating func workerFinished() -> Bool {
        let restart = stopping == .cpuHandoff
        stopping = nil
        return restart
    }
}
