# AUGMIS UI Design System

## Purpose
Maintain a consistent enterprise control-plane visual language across AUGMIS pages.

## Theme source of truth

Canonical file:

```text
apps/web/src/theme.ts
```

## Palette

| Token | Value | Usage |
|---|---|---|
| Primary | `#1f5f8b` | Active navigation, primary buttons, key accents |
| Background default | `#f4f6f8` | Main application workspace |
| Paper | `#ffffff` | Cards, panels, top bars |
| Text primary | `#17212b` | Main headings and body text |
| Text secondary | `#66727d` | Supporting labels, metadata |
| Divider | `#d9e0e5` | Panel/card separators and borders |

Theme mode is **light**.

## Typography

Font stack:

```text
"Segoe UI", Arial, Helvetica, sans-serif
```

Rules:
- `h4`: weight 600, slight negative letter spacing.
- `h5`, `h6`: weight 600.
- Buttons: no uppercase transformation; weight 600.
- Small enterprise metadata frequently uses 9–12px text.
- Section eyebrows use small uppercase text with increased letter spacing.

## Shape and elevation

Global radius:

```text
4px
```

Rules:
- Avoid pill-heavy or excessively rounded dashboard styling.
- Cards should feel structured and enterprise-oriented.
- `MuiCard` has no box shadow and uses a thin divider-color border.
- `MuiPaper` has no background image.
- Buttons have elevation disabled.

## Standard panel language

Preferred:
- white surface,
- `1px solid` divider border,
- low/no shadow,
- compact spacing,
- strong information hierarchy,
- blue used intentionally for selected/primary states.

Avoid:
- random gradients,
- heavy shadows,
- large 16–24px corner radii,
- glassmorphism,
- dark-mode-only components,
- inconsistent one-off color systems.

## AppShell geometry

The current shell establishes:
- top brand bar: `64px` high,
- horizontal primary navigation: minimum `48px`,
- system status strip: minimum `34px`,
- main workspace: responsive horizontal padding (`2` on xs, `3` on md) and vertical padding `3`.

New pages should visually sit inside this geometry rather than creating their own full-page shell.

## Navigation active state

Active navigation uses:
- primary color text,
- `3px` primary bottom border,
- weight 600.

Inactive navigation uses secondary text and transparent bottom border.

Hover:
- background `#f6f8fa`,
- text moves toward primary text color.

## Tenant controls

Tenant selection is global and appears in the top bar.

The selector:
- uses `DomainOutlined`,
- displays `TENANT`,
- uses a compact MUI `Select`,
- shows tenant name + slug,
- uses white background,
- uses approximately `210px` minimum width.

Pages may show a read-only current-tenant summary panel, but should not render a second editable tenant selector.

## Status presentation

Use MUI `Chip` or compact text for status.
Prefer semantic colors:
- success/active/available → success
- suspended/warning/not-ready → warning
- cancelled/error → error

Do not invent a separate status color palette if MUI semantic colors already fit.

## Page pattern

Preferred authenticated page structure:

```tsx
<ProtectedRoute>
  <AppShell>
    <Box>
      {/* page header */}
      {/* tenant/current-context summary when useful */}
      {/* alerts */}
      {/* filters/search/actions */}
      {/* page body */}
    </Box>
  </AppShell>
</ProtectedRoute>
```

## Page header pattern

Recommended:
- small uppercase section label,
- `Typography variant="h4"` title,
- one-line secondary description,
- page actions aligned right (`Refresh`, `Create`, etc.).

## Responsive behavior

- Use MUI responsive values rather than separate mobile-only pages.
- Let horizontal navigation scroll when necessary.
- Hide secondary user metadata where appropriate on small screens.
- Use responsive grids for cards and data panels.
