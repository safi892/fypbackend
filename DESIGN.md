---
name: Code Analyzer
description: A clear C++ editor and reading workspace.
colors:
  blue: "#2454d6"
  blue-hover: "#1b43b3"
  background: "#f5f7fa"
  surface: "#fff"
  foreground: "#1e293b"
  muted: "#626e7f"
  border: "#dce2ea"
  secondary: "#edf1f6"
  secondary-hover: "#e1e7ef"
  secondary-text: "#243247"
  text-action: "#345c9b"
  text-action-hover: "#eaf0f9"
  editor: "#182333"
  editor-toolbar: "#202c3d"
  source: "#e0e8f3"
  source-placeholder: "#91a0b7"
  notice: "#edf2fc"
  notice-text: "#31528a"
  warning: "#fff5e6"
  warning-text: "#865612"
  success: "#e8f4ee"
  success-text: "#246d57"
  error: "#ad3434"
typography:
  headline:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.9px"
  title:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "17px"
    fontWeight: 700
    letterSpacing: "-.25px"
  body:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "14px"
    lineHeight: 1.85
  label:
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: "13px"
    fontWeight: 600
  code:
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace'
    fontSize: "13px"
    lineHeight: 1.85
rounded:
  tag: "5px"
  text-action: "6px"
  field: "7px"
  control: "8px"
  panel: "14px"
  dialog: "16px"
spacing:
  compact: "8px"
  group: "12px"
  inset: "18px"
  section: "24px"
  dialog: "28px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "11px 18px"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-text}"
    rounded: "{rounded.control}"
    padding: "11px 18px"
  button-text:
    backgroundColor: "transparent"
    textColor: "{colors.text-action}"
    rounded: "{rounded.text-action}"
    padding: "8px"
  panel:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.panel}"
  language-tag:
    backgroundColor: "{colors.secondary}"
    rounded: "{rounded.tag}"
    padding: "6px 9px"
---

# Design System: Code Analyzer

## Overview

**Creative North Star: "The C++ reading workspace"**

The shipped interface pairs a graphite source editor with a cool white reading surface. Restrained blue actions, system typography, and generous separation keep attention on entering code and understanding the response. This documents the implementation in `app/web/`; it does not introduce a new visual direction.

**Key Characteristics:**

- Cool white surfaces with graphite source editing.
- Blue actions with plain-language labels.
- System sans for interface text and monospace for source.
- Flat panels with a compact public-access status.

## Colors

The palette uses one blue action accent, cool neutrals, and semantic feedback colors.

### Primary

Blue marks the main analysis action and active navigation. The darker hover color provides immediate button feedback. Text actions use a quieter blue.

### Neutral

White panels sit on the cool page background, separated by fine borders. Dark source and toolbar surfaces distinguish editable code from the light output reading area. Muted text supports headings without competing with them.

### Feedback

Blue notices describe service availability and stale results. Amber marks review requests, green marks completion, and red identifies errors. Every status includes a text label.

## Typography

The interface uses the platform sans stack throughout. The main heading is 30px at weight 650, reducing to 25px on small screens. Panel titles are 17px; output section titles are 14px. Explanations use 14px text with a 1.85 line height and a maximum measure of 70ch. Supporting copy uses 13–15px text; compact metadata uses 11–12px.

Source and API data use the recorded monospace stack, a 1.85 line height, and four-space tab sizing. Source whitespace is preserved. Explanation text wraps and preserves line breaks.

## Layout

The page container is capped at 1540px with 4% horizontal padding. The header is 80px tall. Desktop uses equal editor and results columns separated by 24px; panel headings have 23px vertical and 24px horizontal padding.

At 900px and below, the workspace becomes one column and the page top inset reduces to 30px. At 520px and below, the header becomes 70px tall, navigation links are hidden, panel headings use 20px padding, and footer content stacks. The body minimum width is 320px.

The source editor is 365px tall, 310px on small screens, and 440px from 1600px. Long code scrolls within its surface. Output code is capped at 460px tall; expanded API data at 350px.

## Elevation & Depth

Workspace panels use borders and tonal separation without shadows. Focus uses a 3px blue outline with a 4px offset; the editor outline sits inside its surface.

## Shapes

Panels use 14px corners, buttons and notices use 8px, native fields use 7px, and compact language/status tags use 5px. The dialog uses 16px corners. Fine borders define panels and fields. Source text remains rectangular within the clipped panel.

## Components

Buttons are compact and explicit. Primary and secondary buttons have a 44px minimum height; text actions have a 40px minimum height. Main buttons transition background over 160ms. Disabled controls reduce opacity to 0.6 and display a waiting cursor.

Native selects retain browser keyboard behavior. The source editor adds synchronized line numbers, a character count, example loading, and a clear action. The active navigation item uses a blue underline; public test access remains visible on mobile.

The results surface supports empty, loading, error, completed, review-needed, and stale states. Copy actions sit beside their content headings. Raw API output is available through a native disclosure. Loading uses a one-second linear spinner; reduced-motion preference disables animation and transitions.

Status announcements and visible keyboard focus accompany visual feedback.

## Do's and Don'ts

- Do preserve the distinction between source editing and result reading.
- Do use text labels alongside status colors.
- Do keep code whitespace intact and provide scrolling for long source lines.
- Do retain keyboard focus, labeled controls, and reduced-motion behavior.
- Don't render source or model responses as HTML.
- Don't treat a completion badge as a guarantee of code correctness.
