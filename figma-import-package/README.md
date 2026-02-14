# Sabine Dashboard - Figma Import Package

**Version:** 1.0
**Date:** February 9, 2026
**Designer:** Lead UX/UI Designer

---

## 📦 Package Contents

```
figma-import-package/
├── svgs/                          # 6 SVG mockup files ready to import
│   ├── mockup-01-overview-desktop.svg
│   ├── mockup-02-entities-desktop.svg
│   ├── mockup-03-memories-desktop.svg
│   ├── mockup-04-uploads-desktop.svg
│   ├── mockup-05-component-library.svg
│   └── mockup-06-mobile-entities.svg
├── design-tokens/                 # Design system tokens
│   ├── colors.json
│   ├── typography.json
│   ├── spacing.json
│   └── tokens.css
├── guides/                        # Setup and reference guides
│   ├── figma-setup-checklist.md
│   ├── component-naming-guide.md
│   └── handoff-specifications.md
└── README.md                      # This file
```

---

## 🚀 Quick Start (5 Minutes)

### Step 1: Create New Figma File
1. Open Figma (desktop app or web)
2. Click **"New Design File"**
3. Rename: **"Sabine Dashboard v1.0"**

### Step 2: Import SVG Mockups
**Option A: Drag & Drop (Easiest)**
1. Open Finder/Explorer → Navigate to `figma-import-package/svgs/`
2. Select all 6 SVG files
3. Drag into Figma canvas
4. Done! ✅

**Option B: File Menu**
1. In Figma: `File → Place Image/Video...`
2. Select all 6 SVG files from `svgs/` folder
3. Click anywhere on canvas to place
4. Done! ✅

**Option C: Copy-Paste**
1. Open any `.svg` file in a text editor
2. Copy entire contents
3. In Figma: Right-click canvas → `Paste as SVG`
4. Repeat for each file

### Step 3: Organize Your File
1. Create 3 pages in left sidebar:
   - 📄 **Desktop Views** (Overview, Memories, Entities, Uploads)
   - 📱 **Mobile Views** (Mobile mockups)
   - 🎨 **Components** (Component library)

2. Move imported frames to appropriate pages

### Step 4: Set Up Design Tokens
See `guides/figma-setup-checklist.md` for detailed instructions

---

## 📐 Frame Dimensions

| Mockup | Dimensions | Device |
|--------|-----------|--------|
| Overview Desktop | 1440 × 900 | Desktop |
| Entities Desktop | 1440 × 900 | Desktop |
| Memories Desktop | 1440 × 1200 | Desktop (scrollable) |
| Uploads Desktop | 1440 × 900 | Desktop |
| Component Library | 1200 × 1800 | Reference |
| Mobile Entities | 375 × 812 | iPhone 13/14 |

---

## 🎨 Design Token Setup

### Import Colors
1. In Figma: Click color picker
2. Click "+" to create new color style
3. Use hex codes from `design-tokens/colors.json`

**Quick Import Method:**
- Install **"Design Tokens"** Figma plugin
- Import `design-tokens/colors.json`
- Auto-creates all color styles

### Import Typography
1. Select text element
2. Click text style dropdown
3. Create styles matching `design-tokens/typography.json`

**Font Required:**
- **System Font Stack** (already installed on Mac/Windows)
- Fallback: Inter, Roboto, or SF Pro

---

## 🔧 Converting to Components

After importing, convert these elements to reusable components:

### High Priority Components
- [ ] Primary Button (with variants: default, hover, disabled)
- [ ] Secondary Button
- [ ] Text Input (with variants: default, focused, error)
- [ ] Entity Card
- [ ] Memory Card
- [ ] Domain Badge (4 variants: work, family, personal, logistics)
- [ ] Tag Pill

### How to Create Component
1. Select element in Figma
2. Press `⌥ ⌘ K` (Mac) or `Ctrl + Alt + K` (Windows)
3. Or: Right-click → "Create Component"
4. Rename descriptively (e.g., "Button/Primary/Default")

### Creating Variants
1. Select all button states (default, hover, disabled)
2. Right-click → "Combine as Variants"
3. Set property names:
   - Property: "State"
   - Values: "Default", "Hover", "Disabled"

---

## 📱 Responsive Design Notes

### Desktop Breakpoints
- **Large Desktop:** 1440px+ (primary design)
- **Desktop:** 1024px - 1439px (scale down slightly)
- **Tablet:** 768px - 1023px (switch to single column for entities)

### Mobile Breakpoints
- **Mobile:** 375px - 767px (use mobile mockups)
- **Small Mobile:** 320px - 374px (reduce padding)

### Auto-Layout Tips
1. Select container → Add Auto-Layout (`Shift + A`)
2. Set:
   - **Direction:** Vertical for cards, Horizontal for buttons
   - **Spacing:** 16px for cards, 12px for form fields
   - **Padding:** 24px for containers, 16px for cards
   - **Alignment:** Left for text, Center for buttons

---

## 🎯 Next Steps After Import

### Immediate Tasks (10 min)
- [ ] Import all 6 SVG files
- [ ] Organize into pages (Desktop, Mobile, Components)
- [ ] Name frames descriptively
- [ ] Review for any rendering issues

### Setup Tasks (30 min)
- [ ] Create color styles from `design-tokens/colors.json`
- [ ] Create text styles from `design-tokens/typography.json`
- [ ] Set up 8px spacing grid
- [ ] Create component library

### Collaboration Tasks (ongoing)
- [ ] Share Figma link (view-only or edit access)
- [ ] Add design comments/questions
- [ ] Create prototyp linkages
- [ ] Export assets for development

---

## 🐛 Troubleshooting

### SVG Import Issues

**Problem:** Text appears as shapes instead of editable text
- **Cause:** SVG text converted to paths
- **Fix:** After import, select text → Ungroup → Edit text properties
- **Prevention:** Import as "Flatten" only for complex graphics

**Problem:** Colors don't match design tokens
- **Cause:** SVG uses hex codes, not Figma styles
- **Fix:** Select element → Apply color style from panel
- **Prevention:** Set up color styles before applying

**Problem:** Layout breaks when resizing
- **Cause:** Elements not using Auto-Layout
- **Fix:** Select container → Add Auto-Layout (`Shift + A`)

### Font Issues

**Problem:** "System UI" font not found
- **Fix:** Replace with:
  - **Mac:** SF Pro Text
  - **Windows:** Segoe UI
  - **Web:** Inter (download from Google Fonts)

### Performance Issues

**Problem:** Figma slow with large SVGs
- **Fix:**
  - Flatten unnecessary groups
  - Reduce number of nodes (use Figma's "Simplify" tool)
  - Split into multiple pages

---

## 📚 Additional Resources

### Figma Documentation
- [Importing files](https://help.figma.com/hc/en-us/articles/360040028034)
- [Creating components](https://help.figma.com/hc/en-us/articles/360038662654)
- [Auto-Layout guide](https://help.figma.com/hc/en-us/articles/360040451373)

### Design System Setup
- See `guides/figma-setup-checklist.md` for detailed setup
- See `guides/component-naming-guide.md` for naming conventions
- See `guides/handoff-specifications.md` for developer handoff

### Keyboard Shortcuts
- Create Component: `⌥ ⌘ K` (Mac) / `Ctrl + Alt + K` (Win)
- Auto-Layout: `Shift + A`
- Frame Tool: `F`
- Copy Properties: `⌥ ⌘ C` / `Ctrl + Alt + C`
- Paste Properties: `⌥ ⌘ V` / `Ctrl + Alt + V`

---

## ✅ Success Checklist

Before considering import complete, verify:

- [ ] All 6 SVG files imported without errors
- [ ] Frames are correct dimensions (check against table above)
- [ ] Text is editable (not flattened)
- [ ] Colors match design tokens
- [ ] Organized into logical pages
- [ ] Component library set up (at minimum: buttons, inputs, cards)
- [ ] Auto-Layout applied to key containers
- [ ] Design tokens imported (colors, typography)
- [ ] File shared with collaborators

---

## 🤝 Collaboration Workflow

### Sharing Your Figma File
1. Click "Share" button (top-right)
2. Set permissions:
   - **"Can view"** - For stakeholders/reviewers
   - **"Can edit"** - For design collaborators
3. Copy link and share

### Getting Feedback
**Option 1: Comments**
- Reviewers click anywhere → Add comment
- Designer responds and resolves

**Option 2: Screenshots**
- Export frame: Select → Right-click → "Copy/Paste as PNG"
- Share via Slack/Email with markup

**Option 3: Prototype**
- Connect frames with prototype links
- Share prototype URL for interactive review

---

## 📞 Support

**Questions about the design?**
- Review the original proposal: `../docs/PRD_Sabine_Dashboard_UX_Refresh.md`
- Check component specs: `guides/handoff-specifications.md`

**Technical Figma questions?**
- Figma Help Center: https://help.figma.com
- Figma Community: https://forum.figma.com

**Need design adjustments?**
- Create list of requested changes
- Share screenshot with annotations
- Iterate together!

---

## 🎉 You're Ready!

You now have everything needed to import and work with the Sabine Dashboard designs in Figma.

**Estimated Time:**
- Import: 5 minutes
- Basic setup: 15 minutes
- Full component library: 60 minutes
- Ready to prototype: 90 minutes

**Happy designing! 🎨**
