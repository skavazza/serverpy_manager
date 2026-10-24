# Explorer interface

The explorer serves real files from a shared folder. Its primary workflow is navigating folders, finding files and performing reversible operations.

- Hierarchy: product header with theme/language; file actions; location and view/sort controls; navigation sidebar and file area; operation feedback.
- Visual language: neutral surfaces, blue accent, restrained borders, consistent SVG icons, compact rows and readable cards. Light and dark themes share semantic color tokens.
- Sidebar: quick access, user favorites and expandable folder tree. Trash and recent moves open recovery dialogs.
- States: loading, empty folder/search/trash/favorites/history, search errors and partial results, readonly controls, selection, operation progress, restoration conflicts.
- Responsive behavior: controls wrap; file area remains usable; sidebar becomes a dismissible overlay on narrow screens; dates hide in compact rows.
- Acceptance: existing file operations work in both themes; recursive search shows original locations; deleted files survive restart and can be restored without overwriting; recent moves can be undone; favorites and themes persist; desktop and mobile layouts have no clipping.
