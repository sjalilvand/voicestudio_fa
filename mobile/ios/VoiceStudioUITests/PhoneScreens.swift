import XCTest

final class PhoneScreens: XCTestCase {
    @MainActor private func launch(extra: [String] = []) -> XCUIApplication {
        let app = XCUIApplication(); app.launchArguments = ["--ui-smoke","-AppleLanguages","(en)"] + extra
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); app.buttons["consent.no"].tap()
        app.openSpeak()
        return app
    }
    @MainActor func testRememberedComputerChoiceFallsBackWhileUnpaired() {
        let app = launch(extra: ["-run-on.speak","computer","-run-on.clone","computer","-run-on.dub","computer"])
        XCTAssertTrue(app.buttons["models.get"].exists)
        app.tabButton("Voices").tap(); app.buttons["voices.create"].tap()
        XCTAssertTrue(app.buttons["models.get"].waitForExistence(timeout: 5)); app.buttons["Cancel"].tap()
        app.tabButton("Dub").tap()
        XCTAssertTrue(app.staticTexts["1 Source"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.textFields["dub.source_url"].exists)
    }
    @MainActor func testChangingSpeechModelResetsUnavailablePreset() {
        let app = launch()
        app.buttons["Models"].tap(); app.buttons["choice.option.kokoro-multi-int8"].tap()
        app.buttons["Voice"].tap()
        let search = app.textFields.firstMatch
        XCTAssertTrue(search.waitForExistence(timeout: 5)); search.tap(); search.typeText("Voice 103")
        app.buttons["choice.option.102"].tap()
        XCTAssertEqual(app.buttons["Voice"].value as? String,"Voice 103")
        app.buttons["Models"].tap(); app.buttons["choice.option.kitten-mini-en-fp16"].tap()
        app.buttons["Voice"].tap()
        XCTAssertEqual(app.buttons["choice.option.0"].value as? String,"Selected")
        XCTAssertFalse(app.buttons["choice.option.102"].exists)
    }
    @MainActor func testUnpairedCloneShowsModelGateAndConsent() {
        let app = launch(); app.tabButton("Voices").tap(); app.buttons["voices.create"].tap()
        XCTAssertTrue(app.textFields["voices.clone.name"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["models.get"].exists)
        XCTAssertTrue(app.switches["I have permission"].exists)
        XCTAssertFalse(app.buttons["Create clone"].isEnabled)
        XCTAssertFalse(app.staticTexts["This task currently runs on your paired computer."].exists)
    }
    @MainActor func testUnpairedDubHasSourceLanguagesAndVoiceSteps() {
        let app = launch(); app.tabButton("Dub").tap()
        for step in ["1 Source","2 Languages","3 Voice"] { XCTAssertTrue(app.staticTexts[step].waitForExistence(timeout: 5)) }
        XCTAssertTrue(app.buttons["Choose video or audio"].exists)
        XCTAssertTrue(app.buttons["dub.languages"].exists)
        XCTAssertFalse(app.buttons["dub.start"].isEnabled)
        XCTAssertFalse(app.textFields["dub.source_url"].exists)
        XCTAssertTrue(app.staticTexts["No dubs"].exists)
    }
    @MainActor func testModelsTermsRequireExplicitUncheckedConsent() {
        let app = launch(); app.tabButton("Settings").tap(); app.buttons["Models"].tap()
        let licence = app.buttons["model.licence.kitten-mini-en-fp16"]
        XCTAssertTrue(licence.waitForExistence(timeout: 5)); licence.tap()
        let accept = app.buttons["models.accept"]
        for _ in 0..<15 { if accept.isHittable { break }; app.swipeUp() }
        XCTAssertTrue(accept.exists); XCTAssertFalse(accept.isEnabled)
        let consent = app.switches["models.consent"]
        XCTAssertTrue(consent.exists); consent.tap(); XCTAssertTrue(accept.isEnabled)
        app.buttons["Decline"].tap()
    }
    @MainActor func testCompactDownloadsUseProductNamesAndOneDubAction() {
        let app = launch()
        XCTAssertEqual(app.buttons.matching(identifier: "models.get").count, 1)
        XCTAssertFalse(app.staticTexts["kitten-mini-en-fp16"].exists)
        XCTAssertTrue(app.buttons["models.open"].label.contains("Kitten"))
        app.buttons["models.get"].tap()
        XCTAssertTrue(app.buttons["models.accept"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["models.accept"].isEnabled)
        for _ in 0..<15 { if app.buttons["Decline"].isHittable { break }; app.swipeUp() }
        app.buttons["Decline"].tap()
        app.tabButton("Voices").tap()
        XCTAssertFalse(app.buttons["whisper-tiny-int8"].exists)
        app.tabButton("Dub").tap()
        XCTAssertEqual(app.buttons.matching(identifier: "models.get").count, 1)
        XCTAssertTrue(app.buttons["models.open"].label.contains("3 downloads"))
        XCTAssertFalse(app.staticTexts["NOASSERTION"].exists)
        XCTAssertFalse(app.navigationBars.buttons["Settings"].exists)
    }
    @MainActor func testPaletteSelectionAndDictationActionsClearTheTabBar() {
        let app = launch(); app.tabButton("Dictate").tap()
        let navigation = ["Home", "Voices", "Dub", "Dictate", "Settings"].map { app.tabButton($0) }
        for identifier in ["dictate.copy", "dictate.share"] {
            let action = app.buttons[identifier]
            XCTAssertTrue(action.exists)
            for tab in navigation {
                XCTAssertTrue(tab.exists)
                XCTAssertFalse(action.frame.intersects(tab.frame), "Dictation action overlaps navigation")
            }
        }
        app.tabButton("Settings").tap()
        app.buttons["mobile.settings.light_palette"].tap()
        let studio = app.buttons["choice.option.default"]
        XCTAssertTrue(studio.waitForExistence(timeout: 5)); XCTAssertEqual(studio.value as? String, "Selected")
        app.buttons["choice.option.canopy"].tap()
        app.buttons["mobile.settings.light_palette"].tap()
        XCTAssertEqual(app.buttons["choice.option.canopy"].value as? String, "Selected")
    }
    @MainActor func testConnectAndPrivacyKeepDetailsCollapsed() {
        let app = launch(); app.tabButton("Settings").tap()
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
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); XCTAssertTrue(app.staticTexts["Saved on this phone. Nothing is sent."].exists); capture("Consent",app); app.buttons["consent.no"].tap(); capture("Home",app); app.openSpeak()
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 5)); capture("Speak-phone",app)
        app.tabButton("Voices").tap(); capture("Voices-phone",app)
        app.buttons["voices.create"].tap(); XCTAssertTrue(app.textFields["voices.clone.name"].waitForExistence(timeout: 5)); capture("Clone-phone",app); app.buttons["Cancel"].tap()
        app.tabButton("Dub").tap(); XCTAssertEqual(app.buttons.matching(identifier: "models.get").count, 1); capture("Dub-phone",app)
        app.tabButton("Dictate").tap(); capture("Dictate-phone",app)
        app.tabButton("Settings").tap(); capture("Settings",app)
        app.buttons["mobile.settings.light_palette"].tap()
        XCTAssertTrue(app.buttons["choice.option.default"].waitForExistence(timeout: 5)); capture("Palette-picker",app); app.buttons["Close"].tap()
        app.buttons["Language"].tap(); capture("Language-picker",app); app.buttons["Close"].tap()
        app.buttons["Models"].tap(); capture("Models",app)
        app.buttons["model.licence.kitten-mini-en-fp16"].tap(); capture("Model-terms",app); app.buttons["Close"].tap()
        let adaptiveBack = app.buttons["BackButton"]
        if adaptiveBack.exists { adaptiveBack.tap() } else { app.navigationBars.buttons.firstMatch.tap() }
        XCTAssertTrue(app.buttons["settings.connect"].waitForExistence(timeout: 5))
        app.buttons["settings.connect"].tap(); capture("Connect",app)
        app.buttons["Enter address"].tap(); capture("Connect-address",app)
    }
    @MainActor func testPairedComputerScreens() {
        let app = XCUIApplication(); app.launchArguments = ["--ui-smoke","-AppleLanguages","(en)"]
        app.launch(); XCTAssertTrue(app.buttons["consent.no"].waitForExistence(timeout: 10)); app.buttons["consent.no"].tap()
        app.tabButton("Settings").tap(); app.buttons["settings.connect"].tap(); app.buttons["Enter address"].tap()
        let address = app.textFields["connect.url"]; address.tap(); address.typeText("http://127.0.0.1:3900")
        app.buttons["keyboard.done"].tap(); app.buttons["connect.submit"].tap(); app.openSpeak()
        XCTAssertTrue(app.textViews["speak.text"].waitForExistence(timeout: 10)); capture("Speak-computer",app)
        for tab in ["Voices","Dub","Dictate"] { app.tabButton(tab).tap(); capture(tab+"-computer",app) }
    }
}
