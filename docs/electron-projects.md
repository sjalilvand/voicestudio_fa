# Electron projects

Open Projects from the sidebar, command search, or Dubbing header. Current dubbing work can be saved with a name or saved as a new copy. Projects use the existing backend `/projects` database and Tauri state format.

Opening a project asks before replacing the current draft. Active dubbing work and unresolved task recovery prevent switching. Deletion requires confirmation, removes only the saved project record, and detaches it from the current draft. It does not delete source media or generated audio.

Segment edits, selected language, source job, and available tracks are restored. Unexposed legacy options and per-segment metadata are retained when saving. Renderer reload preserves the active project identity. This does not recreate missing source media or imply an interrupted backend job is running.

The library combines backend dubbing projects, local IndexedDB Stories and Audiobooks, saved
voice profiles, transcription history, generated takes, export history and completed longform
renders. A stable secondary sidebar filters each source and shows live counts; one search and the
list/grid switch operate without moving the workspace origin. At compact widths the global
sidebar becomes its icon rail, matching the other secondary-sidebar workspaces.

Opening a book or story restores its saved draft after confirmation; deletion detaches the draft
without removing generated media. Inline rename changes only the saved name: dubbing uses the
lightweight PATCH endpoint, and local books rename the latest durable record inside the serialized
write queue. Profile rows select the voice in cloning, transcript and take rows reuse their script,
take and completed-render rows preview through Vidstack, and export rows reveal the destination.

Verification: `electron/tests/projects-smoke.mjs` exercises the UI with a mocked project API; project-format unit tests check legacy round trips and malformed segments. A separate disposable fixture passed create/read/update/delete against the running backend.

Browser regressions verify all-source counts and profile/transcript filters alongside local book
save, unified-list rename, reload, confirmed open with original script intact, and deletion; dubbing
rename preserves unexposed options and updates the current save name. A disposable real backend
rename/read/delete round trip confirmed state preservation.
