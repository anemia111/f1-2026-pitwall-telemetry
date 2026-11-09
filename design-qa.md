# Race Leaderboard design QA

- Reference: user-provided 678 × 595 Race Leaderboard panel. It contains live text and data graphics without raster assets.
- Browser capture: Codex in-app Browser, 650 × 512 viewport. Compared the panel header, column order, team-color position badges, selected row, tyre markers, and three miniature progress rails. At smaller widths the table scrolls within its panel.
- Interactions: LIVE/GAP switched the interval column. LAP RECORDS loaded the archived lap list and 30 mini-sector rows for the selected lap. Checked for browser console errors and found none.
- Intentional adaptations: ERS uses reported energy in MJ. TYRE uses reported compound and age, and USED shows maximum wheel wear when all four values are present. The rails show current lap progress.
- final result: passed
