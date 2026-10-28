/**
 * Workspace navigation model — shared by both navigation presentations.
 *
 * The icon rail (`NavRail`) and the titlebar tab strip (`TitleTabs`) are two
 * skins of the SAME list; Settings → Appearance → Navigation style picks which
 * one renders. Declaring the workspaces once here means a new workspace shows
 * up in both skins from a single edit and the two can't drift apart.
 *
 * `accent` is the workspace's hue. Both skins spend it the same way: the
 * ACTIVE item wears it (rail indicator bar / tab top rule + icon), inactive
 * items stay neutral, so the chrome never turns into a colour chart.
 */
import {
  Globe,
  Fingerprint,
  Film,
  FolderOpen,
  Settings2,
  Library,
  FileText,
  BookOpen,
  BookMarked,
  Boxes,
} from 'lucide-react';

/** The workspaces, in navigation order. `tKey` resolves as `nav.<tKey>`. */
export const NAV_ITEMS = [
  { id: 'launchpad', Icon: Globe, tKey: 'launchpad', accent: '#f3a5b6' },
  // CLEAN-ROOM (spec W11-residue §E10): nav entries studio, dub, stories, audiobook, gallery, transcriptions, projects
  // Engines + model weights. Sits last in the workspace list (immediately above
  // Settings in the footer) because it configures the app rather than producing
  // anything — it is where the defaults every other workspace runs on are set.
  { id: 'catalogue', Icon: Boxes, tKey: 'catalogue', accent: '#689d6a' },
];

/** Pinned to the end of the nav (rail footer / tab-strip tail). */
export const NAV_FOOTER_ITEMS = [
  { id: 'settings', Icon: Settings2, tKey: 'settings', accent: '#fabd2f' },
];
