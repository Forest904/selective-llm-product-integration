# Mosaic Educational Demo Website

Static Astro site for M5. It explains the Mosaic assignment pipeline with
curated demo data, data-flow animation, and fixture-labeled research snapshots.

## Local development

```bash
pnpm --filter @mosaic/web dev
```

## Static build

```bash
pnpm --filter @mosaic/web build
```

The Cloudflare Pages output directory is:

```text
apps/web/dist
```

The app uses Astro static output with Astro components and small page-scoped
TypeScript controllers for the interactive pipeline and concept explorer. It
has no React runtime, hydration islands, or backend runtime features.
