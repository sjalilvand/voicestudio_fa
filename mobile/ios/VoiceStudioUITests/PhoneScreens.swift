import XCTest

final class PhoneScreens: XCTestCase {
    @MainActor private func launch(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication(); app.launchArguments = ["--ui-smoke","-AppleLanguages","(en)"] + extra
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); app.buttons["consent.no"].tap()
        return app
    }
    @MainActor func testRememberedComputerChoiceFallsBackWhileUnpaired() {
        let app = launch(extra: ["-run-on.speak","computer","-run-on.clone","computer","-run-on.dub","computer"])
        XCTAssertTrue(app.buttons["Open Models"].exists)
        app.tabBars.buttons["Voices"].tap(); app.buttons["voices.create"].tap()
        XCTAssertTrue(app.buttons["Open Models"].waitForExistence(timeout: 5)); app.buttons["Cancel"].tap()
        app.tabBars.buttons["Dub"].tap()
        XCTAssertTrue(app.staticTexts["1 Source"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["dub.source_url"].exists)
    }
    @MainActor func testUnpairedCloneShowsModelGateAndConsent() {
        let app = launch(); app.tabBars.buttons["Voices"].tap(); app.buttons["voices.create"].tap()
        XCTAssertTrue(app.textFields["voices.clone.name"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["Open Models"].exists)
        XCTAssertTrue(app.switches["I have permission"].exists)
        XCTAssertFalse(app.buttons["Create clone"].isEnabled)
        XCTAssertFalse(app.staticTexts["This task currently runs on your paired computer."].exists)
    }
    @MainActor func testUnpairedDubHasSourceLanguagesAndVoiceSteps() {
        let app = launch(); app.tabBars.buttons["Dub"].tap()
        for step in ["1 Source","2 Languages","3 Voice"] { XCTAssertTrue(app.staticTexts[step].waitForExistence(timeout: 5)) }
        XCTAssertTrue(app.buttons["Choose video or audio"].exists)
        XCTAssertTrue(app.buttons["dub.languages"].exists)
        XCTAssertFalse(app.buttons["dub.start"].isEnabled)
        XCTAssertFalse(app.textFields["dub.source_url"].exists)
        XCTAssertTrue(app.staticTexts["No dubs"].exists)
    }
    @MainActor func testModelsTermsRequireExplicitUncheckedConsent() {
        let app = launch(); app.tabBars.buttons["Settings"].tap(); app.buttons["Models"].tap()
        let licence = app.buttons["model.licence.kitten-mini-en-fp16"]
        XCTAssertTrue(licence.waitForExistence(timeout: 5)); licence.tap()
        let accept = app.buttons["models.accept"]
        for _ in 0..<15 { if accept.isHittable { break }; app.swipeUp() }
        XCTAssertTrue(accept.exists); XCTAssertFalse(accept.isEnabled)
        let consent = app.switches["models.consent"]
        XCTAssertTrue(consent.exists); consent.tap(); XCTAssertTrue(accept.isEnabled)
        app.buttons["Decline"].tap()
    }
    @MainActor func testConnectAndPrivacyKeepDetailsCollapsed() {
        let app = launch(); app.tabBars.buttons["Settings"].tap()
        XCTAssertFalse(app.staticTexts.containing(NSPredicate(format: "label BEGINSWITH %@","On-device tasks send nothing")).firstMatch.exists)
        app.buttons["settings.connect"].tap()
        XCTAssertTrue(app.buttons["Scan QR code"].exists)
        XCTAssertFalse(app.textFields["connect.url"].exists)
        app.buttons["Enter address"].tap(); XCTAssertTrue(app.textFields["connect.url"].exists)
        XCTAssertFalse(app.secureTextFields.firstMatch.exists)
        app.buttons["More"].tap(); XCTAssertTrue(app.secureTextFields.firstMatch.exists)
    }
}

/// Xcode test attachments are the reviewable screen tour; no screenshots are fabricated by CLT checks.
final class ScreenshotTour: XCTestCase {
    @MainActor private func capture(_ name: String,_ app: XCUIApplication) {
        let attachment = XCTAttachment(screenshot: app.screenshot()); attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    @MainActor func testPhoneFirstScreens() {
        let app = XCUIApplication(); app.launchArguments = ["--ui-smoke","-AppleLanguages","(en)"]
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); capture("Consent",app); app.buttons["consent.no"].tap()
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 5)); capture("Speak-phone",app)
        app.tabBars.buttons["Voices"].tap(); capture("Voices-phone",app)
        app.buttons["voices.create"].tap(); XCTAssertTrue(app.textFields["voices.clone.name"].waitForExistence(timeout: 5)); capture("Clone-phone",app); app.buttons["Cancel"].tap()
        app.tabBars.buttons["Dub"].tap(); capture("Dub-phone",app)
        app.tabBars.buttons["Dictate"].tap(); capture("Dictate-phone",app)
        app.tabBars.buttons["Settings"].tap(); capture("Settings",app)
        app.buttons["Models"].tap(); capture("Models",app)
        app.buttons["model.licence.kitten-mini-en-fp16"].tap(); capture("Model-terms",app); app.buttons["Close"].tap()
        app.navigationBars.buttons.firstMatch.tap(); app.buttons["settings.connect"].tap(); capture("Connect",app)
        app.buttons["Enter address"].tap(); capture("Connect-address",app)
    }
    @MainActor func testPairedComputerScreens() {
        let app = XCUIApplication(); app.launchArguments = ["--ui-smoke","-AppleLanguages","(en)"]
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); app.buttons["consent.no"].tap()
        app.tabBars.buttons["Settings"].tap(); app.buttons["settings.connect"].tap(); app.buttons["Enter address"].tap()
        let address = app.textFields["connect.url"]; address.tap(); address.typeText("http://127.0.0.1:3900")
        app.buttons["keyboard.done"].tap(); app.buttons["connect.submit"].tap()
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 10)); capture("Speak-computer",app)
        for tab in ["Voices","Dub","Dictate"] { app.tabBars.buttons[tab].tap(); capture(tab+"-computer",app) }
    }
}
