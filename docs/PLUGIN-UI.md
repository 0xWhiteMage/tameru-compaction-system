# One interface for every Tameru plugin

Every harness plugin shows the same small interface, so that a person who has used Tameru in one agent harness recognises it in another. This page is the spec. The words are in [`ui-vocabulary.json`](ui-vocabulary.json) and the drawings in [`ui-icons.json`](ui-icons.json); each plugin keeps a copy of both and tests that its own strings and paths equal them, the way it already proves its vendored engine is identical.

The design was reviewed by five specialists (interaction, layout, user experience, typography, graphic design) over four rounds, and all five passed it. Nothing here is a claim about savings: the plugin shows what it did, never what it is worth.

What is shared: the **bar**, the **icon meanings**, the **strength names**, the **words**. What is not: the **details view** (each host has its own container and its own conventions) and each host's own colours, radii and fonts, which the plugin takes from the host's theme.

## The bar

```
 ✦ Tameru (ためる)   Idle until 59% full          ◔ 55% full  │  Normal ▾   ≡ 3   📌 2
 └ identity and status (the phrase is the only part that shrinks)   └ reading   └ controls
```

| Element | Spec |
|---|---|
| **Star** | The Tameru star ([`ui-icons.json`](ui-icons.json)), 14 px, replaces any status dot. Its colour is the state: idle = tertiary; working = the host's accent, pulsing only if motion is allowed; Off = tertiary at 45% opacity; problem = the host's error colour. **No green.** |
| **Name** | `Tameru` weight 600, primary colour; `(ためる)` in `<small lang="ja">`, one size down, weight 400, tertiary, ASCII parentheses. Never truncated. |
| **Status phrase** | One phrase from the list below, tertiary, ellipsis, a button that opens the results. |
| **Gauge** | A 14 px ring (r 6, stroke 2, round cap, filling clockwise from 12 o'clock), a 1.5 px notch where Tameru starts, then `55% full`. At narrow widths "full" hides first, then the figure; the ring never hides. Hover: tokens in use, where Tameru starts, where the host compacts. |
| **Separator** | 1 × 16 px; everything after it is a control. |
| **Strength** | One menu button: **Off · Less · Normal · More**, each with its one-line explanation and a scope line. It replaces any pause button. |
| **Results launcher** | List icon and the number of outputs the AI currently sees shortened. Kept outputs are not counted; `0` stays clickable. Toggles the details on results. |
| **Pins launcher** | Pin icon and the pin count. Toggles the details on pins. There is no chevron. |

The bar is always one line. Controls are 28 px targets, 4 px apart; icons are 14 px, one outline weight, tertiary at rest and secondary on hover.

### Status phrases, in priority order

Not connected · Not running · Not running: retrying · Problem · Applies at next step (or next message) · Off · `N outputs shortened` · `N kept in full` · `Idle until P% full` · Idle. The exact strings, with Chinese, are in the vocabulary file. The raw text of an error never appears on the bar, only in the details.

## Icons: one meaning each

| Icon | Means | Never means |
|---|---|---|
| Star (Tameru's) | Tameru and its state | |
| Pin | A pinned instruction | Keeping an output |
| Lock (Tameru's; outline / filled) | **Keep**: the AI sees this output in full until you release it | |
| Undo arrow (Tameru's) | **Restore**: full for the next few replies | |
| Eye | Look at the text yourself | Changing what the AI sees |
| List | Shortened results | |

The star, lock, undo arrow and size arrow are Tameru's own drawings and are identical in every plugin. Close, chevrons, trash, plus and warning are the host's.

## Words

- **"AI"**, never "model". **"context"**, never "working memory". **Shortened**, **Keep / Kept / Release**, **Restore**, **Pins**. Sizes are in **characters**, and a list says so once (the Hermes table keeps exact tokens; see below).
- Nothing on a bar or in a card says or implies a cost or a saving. A shared test fails on the words `cost`, `price`, `sav…`, `pay…`, `cheap…`, `freed`, `gain` and their Chinese equivalents (English words match from the start of a word, so "again" is fine).
- No "new" badge and no unread tracking. No "Freed" figure on the bar.
- Every error says what happened, that the chat is unchanged, and what to do or when it retries.

## Colour

Three meanings only: the accent = working; the host's error colour = a problem; everything else is the host's label greys. Dim text uses the tertiary colour, never opacity. Tertiary text must measure at least 4.5 : 1 on its surface in light and dark. If a host's tertiary colour falls short (the Harness's is 3.66 : 1 in its light theme), blend part of the primary colour into it until it clears the bar (the DeepSeek plugin blends 30%: 6.03 : 1 light, 8.84 : 1 dark).

## Type

Two sizes, taken from the host's own font setting: base and small (base − 1 px). Weights 400, 500, 600, and 600 only for the word "Tameru". Numbers are tabular. Boxes use `min-height` so that larger user text grows them. No bare pixel `font-size`.

## Controls

| Control | Rest | Hover | On / open | Focus |
|---|---|---|---|---|
| Launchers | tertiary | secondary, no fill | hover-fill + primary while its tab shows | 2 px accent ring |
| Status phrase | tertiary | secondary on a 6 px pill | | ring |
| Result row | none | hover fill on the main area only | | ring |
| Keep | lock outline + "Keep", tertiary | own pill | filled lock + "Kept" in **primary** (accent means working) | ring |
| Tabs | tertiary | secondary | filled + primary | ring |

A problem on the bar clears on the next success of the same kind, or 10 seconds after the user has seen it in the details. A failed strength change puts the menu back to the value actually in force.

## Result rows and the viewer (wherever the host shows them)

- A row says what was run, not a number: the tool name, then the start of its command or path. The reference number appears only in the viewer title.
- Sizes are whole K, `<1K` below a thousand, whole M above, in an aligned `from → to` group with the arrow drawn, and one `characters` caption per list.
- Kept outputs sit below a divider `Kept in full · N`.
- The viewer has one header: back, title, `AI sees | Original`, Keep, close. It opens on "AI sees" the first time and on the last side chosen afterwards. Text is monospace at the small size, wraps inside its box, never widens its container.

## Where each plugin follows this

The DeepSeek Harness plugin (`dsh-tameru-plugin`, in development; repository not publicly available at this review) draws the bar as a pill built like that harness's own goal bar and opens a floating card. The [Hermes plugin](https://github.com/0xWhiteMage/hermes-tameru-plugin) (from 1.10.0) keeps its card head and its table. Both use the same strings, the same drawings and the same meanings. A new plugin follows the same rules in its own host's idiom and adds the two JSON files to its tests.

Where a host differs, the difference is in the host, not in the words:

| | DeepSeek Harness plugin | Hermes plugin |
|---|---|---|
| Strength scope line | `Applies to all chats.` | `This chat.` |
| Waiting phrase | `Applies at next step` | `Applies at next message` |
| Strength menu | a pop-up menu | opens inline under the bar, because the app's composer area clips pop-ups |
| Details view | floating card with two tabs | the results table (time, source, lines, reduction, tokens reduced, status, actions) and the pins list in the same container |
| Sizes | characters | the table keeps exact tokens, which Hermes reports itself |
| Removed-text figure | none | one line under the table (`about N% of the context removed`), never on the bar |
| Extra phrases | none | `Open a chat`, `Loading…` and `Compacting…` (Hermes reports compaction as an event); they are host states, not part of the shared list |
| Off | sets `shorten` off | pauses the chat's tuner; choosing Less, Normal or More from Off turns Tameru on first |

In Hermes, Less, Normal and More are the existing `/tameru bias` words `detail`, `balanced` and `save`, so commands and saved state did not change.
