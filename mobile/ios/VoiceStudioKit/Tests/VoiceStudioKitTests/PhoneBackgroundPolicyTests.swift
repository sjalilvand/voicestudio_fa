import Testing
import Foundation
@testable import VoiceStudioKit

@Test func gpuContinuationRequiresSupportedResourceAndAnAttachedGPUGrant() {
    #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: .continuedGPU,supportsGPU: true,allowCPUFallback: false,cpuAvailable: true) == .continueCurrent)
    for grant in [PhoneBackgroundGrant.none,.finiteCPU,.continuedCPU] {
        #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: grant,supportsGPU: true,allowCPUFallback: false,cpuAvailable: true) == .checkpointAndPause)
    }
    #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: .continuedGPU,supportsGPU: false,allowCPUFallback: false,cpuAvailable: true) == .checkpointAndPause)
}
@Test func deniedOrUnsupportedGPUOnlyHandsOffWithConsentCPUImplementationAndRuntime() {
    for supported in [true,false] {
        for grant in [PhoneBackgroundGrant.finiteCPU,.continuedCPU] {
            #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: grant,supportsGPU: supported,allowCPUFallback: true,cpuAvailable: true) == .restartOnCPU)
            #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: grant,supportsGPU: supported,allowCPUFallback: true,cpuAvailable: false) == .checkpointAndPause)
        }
    }
    #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .automatic,grant: .none,supportsGPU: false,allowCPUFallback: true,cpuAvailable: true) == .checkpointAndPause)
}
@Test func cpuGrantExpirationPausesAndExplicitStopsOverrideAutomaticRestart() {
    #expect(PhoneBackgroundPolicy.decision(requiresGPU: true,compute: .cpuOnly,grant: .continuedCPU,supportsGPU: false,allowCPUFallback: true,cpuAvailable: true) == .continueCurrent)
    #expect(PhoneBackgroundPolicy.decision(requiresGPU: false,compute: .automatic,grant: .none,supportsGPU: true,allowCPUFallback: true,cpuAvailable: true) == .checkpointAndPause)
    for reason in [PhoneJobRestartGate.Stop.user,.expired,.power] {
        var gate = PhoneJobRestartGate(); gate.request(.cpuHandoff); gate.request(reason)
        let restart = gate.workerFinished(); #expect(!restart)
    }
    var gate = PhoneJobRestartGate(); gate.request(.cpuHandoff)
    let first = gate.workerFinished(), second = gate.workerFinished()
    #expect(first); #expect(!second)
}
@Test func computeChoiceReachesDetachedWorkerAndNeverLeaksToOtherJobs() async throws {
    let cpu = NativeExecutionContext.$compute.withValue(.cpuOnly) { NativeExecutionContext.detached { NativeExecutionContext.compute } }
    let normal = NativeExecutionContext.detached { NativeExecutionContext.compute }
    #expect(try await cpu.value == .cpuOnly); #expect(try await normal.value == .automatic)
    #expect(NativeExecutionContext.compute == .automatic)
}
@Test func cpuReplacementWaitsForCancelledNativeCleanupBeforeAcquiringTheLease() async throws {
    actor Trace { var events: [String] = []; func record(_ value: String) { events.append(value) } }
    let trace = Trace()
    let original = Task {
        try await NativeLease.shared.acquire()
        await trace.record("gpu-started")
        do { try await Task.sleep(for: .seconds(60)) } catch {}
        await trace.record("gpu-cleaned")
        await NativeLease.shared.release()
    }
    while await trace.events.isEmpty { await Task.yield() }
    var gate = PhoneJobRestartGate(); gate.request(.cpuHandoff); original.cancel()
    _ = try await original.value
    if gate.workerFinished() {
        try await NativeLease.shared.acquire(); await trace.record("cpu-started"); await NativeLease.shared.release()
    }
    #expect(await trace.events == ["gpu-started","gpu-cleaned","cpu-started"])
}
