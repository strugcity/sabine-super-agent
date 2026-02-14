# Figma Setup Checklist

Complete these steps to set up your Sabine Dashboard design file properly.

---

## ✅ Phase 1: File Structure (10 min)

### Create Pages
- [ ] Create page: **"📄 Desktop Views"**
- [ ] Create page: **"📱 Mobile Views"**
- [ ] Create page: **"🎨 Components"**
- [ ] Create page: **"📐 Design System"**
- [ ] (Optional) Create page: **"🚧 Work in Progress"**

### Import SVG Files
- [ ] Import `mockup-01-overview-desktop.svg` → Desktop Views page
- [ ] Import `mockup-02-entities-desktop.svg` → Desktop Views page
- [ ] Import `mockup-03-memories-desktop.svg` → Desktop Views page
- [ ] Import `mockup-04-uploads-desktop.svg` → Desktop Views page
- [ ] Import `mockup-05-component-library.svg` → Components page
- [ ] Import `mockup-06-mobile-entities.svg` → Mobile Views page

### Organize Frames
- [ ] Rename each frame descriptively:
  - "Overview - Desktop (1440)"
  - "Entities - Desktop (1440)"
  - "Memories - Desktop (1440)"
  - "Uploads - Desktop (1440)"
  - "Mobile - Entities (375)"
- [ ] Align frames horizontally with 100px spacing
- [ ] Add section labels using text tool

---

## ✅ Phase 2: Color Styles (15 min)

### Create Color Library
Open `design-tokens/colors.json` as reference

**Method 1: Manual Creation**
1. Click any color in Figma
2. Click "+" icon in color styles panel
3. Name using format: `Color/Category/Name`
4. Example: `Color/Primary/Blue-600`

**Method 2: Plugin (Recommended)**
1. Install plugin: **"Design Tokens"** or **"Styles Generator"**
2. Import `colors.json`
3. Auto-creates all color styles

### Required Color Styles
Primary Colors:
- [ ] `Color/Primary/Blue-50` (#DBEAFE)
- [ ] `Color/Primary/Blue-600` (#3B82F6)
- [ ] `Color/Primary/Blue-700` (#2563EB)
- [ ] `Color/Primary/Blue-900` (#1E40AF)

Neutral Colors:
- [ ] `Color/Gray/50` through `Color/Gray/900` (9 shades)

Semantic Colors:
- [ ] `Color/Success` (#10B981)
- [ ] `Color/Success/Light` (#D1FAE5)
- [ ] `Color/Error` (#EF4444)
- [ ] `Color/Error/Light` (#FEE2E2)
- [ ] `Color/Warning` (#F59E0B)
- [ ] `Color/Warning/Light` (#FEF3C7)

Domain Colors:
- [ ] `Color/Domain/Work` (#3B82F6)
- [ ] `Color/Domain/Work-Light` (#DBEAFE)
- [ ] `Color/Domain/Family` (#EC4899)
- [ ] `Color/Domain/Family-Light` (#FBCFE8)
- [ ] `Color/Domain/Personal` (#8B5CF6)
- [ ] `Color/Domain/Personal-Light` (#E9D5FF)
- [ ] `Color/Domain/Logistics` (#10B981)
- [ ] `Color/Domain/Logistics-Light` (#D1FAE5)

### Apply Color Styles
- [ ] Select elements using raw colors
- [ ] Replace with named color styles
- [ ] Verify consistency across all frames

---

## ✅ Phase 3: Text Styles (15 min)

### Font Setup
- [ ] Verify system fonts available:
  - **Mac:** SF Pro Text (default)
  - **Windows:** Segoe UI (default)
  - **Web/Fallback:** Download Inter from Google Fonts

### Create Text Styles
Open `design-tokens/typography.json` as reference

Headings:
- [ ] `Text/Heading/H1` - 36px Bold
- [ ] `Text/Heading/H2` - 24px Bold
- [ ] `Text/Heading/H3` - 20px Semibold (600)
- [ ] `Text/Heading/H4` - 18px Semibold (600)

Body Text:
- [ ] `Text/Body/Large` - 16px Regular
- [ ] `Text/Body/Default` - 14px Regular
- [ ] `Text/Body/Small` - 12px Regular

Special:
- [ ] `Text/Label` - 12px Medium (500)
- [ ] `Text/Button` - 14px Semibold (600)
- [ ] `Text/Code` - 14px Regular Mono

### Text Style Properties
For each text style, set:
1. **Font Family:** -apple-system (or fallback)
2. **Font Size:** Per typography.json
3. **Font Weight:** Per typography.json
4. **Line Height:**
   - Headings: 125% (tight)
   - Body: 150% (normal)
5. **Letter Spacing:**
   - Large headings: -0.025em
   - Body: 0 (none)
   - Labels: +0.025em

### Apply Text Styles
- [ ] Select all text elements
- [ ] Apply appropriate text styles
- [ ] Remove direct text formatting

---

## ✅ Phase 4: Layout Grid (5 min)

### Desktop Grid (1440px)
- [ ] Select desktop frames
- [ ] Click "+" next to Layout Grid
- [ ] Settings:
  - **Type:** Columns
  - **Count:** 12
  - **Gutter:** 24px
  - **Margin:** 32px
  - **Color:** Red 10% opacity

### Mobile Grid (375px)
- [ ] Select mobile frames
- [ ] Add Layout Grid
- [ ] Settings:
  - **Type:** Columns
  - **Count:** 4
  - **Gutter:** 16px
  - **Margin:** 16px
  - **Color:** Red 10% opacity

### 8px Baseline Grid
- [ ] Add second grid to all frames
- [ ] Settings:
  - **Type:** Rows
  - **Size:** 8px
  - **Color:** Blue 5% opacity

---

## ✅ Phase 5: Components (30 min)

### Create Base Components

**Buttons:**
- [ ] Select primary button → Create Component (`⌥⌘K`)
- [ ] Name: `Button/Primary`
- [ ] Duplicate for hover state
- [ ] Duplicate for disabled state
- [ ] Select all 3 → "Combine as Variants"
- [ ] Property name: "State"
- [ ] Values: "Default", "Hover", "Disabled"

Repeat for:
- [ ] `Button/Secondary`
- [ ] `Button/Destructive`
- [ ] `Button/Ghost`

**Form Inputs:**
- [ ] Create component: `Input/Text`
- [ ] Variants: "Default", "Focused", "Error"
- [ ] Create component: `Input/Select`
- [ ] Create component: `Input/Textarea`

**Cards:**
- [ ] Create component: `Card/Entity`
- [ ] Add Auto-Layout (`Shift+A`):
  - Direction: Vertical
  - Spacing: 12px
  - Padding: 20px
  - Fill: Hug contents
- [ ] Create component: `Card/Memory`
- [ ] Create component: `Card/Stats`

**Badges:**
- [ ] Create component: `Badge/Domain`
- [ ] Variants: "Work", "Family", "Personal", "Logistics"
- [ ] Create component: `Badge/Tag`
- [ ] Create component: `Badge/Importance`

### Component Organization
Move all components to **"🎨 Components"** page:
- [ ] Group buttons together
- [ ] Group form inputs together
- [ ] Group cards together
- [ ] Group badges together
- [ ] Add section labels

---

## ✅ Phase 6: Auto-Layout (20 min)

Add Auto-Layout to key containers for responsive design.

### Desktop Views
For each major section:
1. [ ] Select container
2. [ ] Press `Shift+A` (Add Auto-Layout)
3. [ ] Configure:
   - **Direction:** Vertical for stacked content, Horizontal for rows
   - **Spacing:** 16px for cards, 24px for sections
   - **Padding:** 32px for page edges, 20px for cards
   - **Alignment:** Left for content, Center for buttons
   - **Resizing:** Hug for buttons, Fill for containers

### Priority Areas for Auto-Layout:
- [ ] Stats cards row (Horizontal, gap: 20px)
- [ ] Quick actions buttons (Horizontal, gap: 20px)
- [ ] Entity card grid (Vertical, gap: 16px)
- [ ] Memory stream (Vertical, gap: 16px)
- [ ] Form containers (Vertical, gap: 12px)

### Mobile Views
- [ ] Add Auto-Layout to all mobile containers
- [ ] Set to stack vertically
- [ ] Reduce padding from 32px → 16px
- [ ] Test responsiveness by resizing frames

---

## ✅ Phase 7: Interactive Prototype (15 min)

### Create Prototype Connections
1. [ ] Switch to Prototype tab (right panel)
2. [ ] Click on tab button → Drag to corresponding frame
3. [ ] Settings:
   - **Interaction:** On Click
   - **Action:** Navigate to
   - **Animation:** Instant (tabs) or Dissolve (modals)

### Key Interactions to Prototype:
- [ ] Tab navigation (Overview ↔ Memories ↔ Entities ↔ Uploads)
- [ ] "+ New Entity" button → Entity form modal
- [ ] "View Details" → Entity detail view
- [ ] Search bar → Search results
- [ ] Filter dropdown → Filtered view
- [ ] Mobile: Bottom nav → Tab views

### Test Prototype
- [ ] Click "Play" button (top-right)
- [ ] Test all navigation flows
- [ ] Test on mobile device size
- [ ] Fix any broken links

---

## ✅ Phase 8: Collaboration Setup (5 min)

### Share Settings
- [ ] Click "Share" button
- [ ] Set permissions:
  - **Developers:** Can view + Can inspect
  - **Designers:** Can edit
  - **Stakeholders:** Can view
- [ ] Copy link
- [ ] Share via Slack/Email

### Add Documentation
- [ ] Add cover page with:
  - Project title
  - Version number
  - Last updated date
  - Contact info
- [ ] Add page descriptions
- [ ] Add component documentation notes

### Enable Comments
- [ ] Share link with "Can comment" permission
- [ ] Add initial comments with questions
- [ ] Set up notification preferences

---

## ✅ Phase 9: Developer Handoff (10 min)

### Inspect Mode
- [ ] Enable "Dev Mode" (toggle in top toolbar)
- [ ] Verify measurements are accurate
- [ ] Check exported CSS matches design tokens

### Export Settings
For icon assets:
- [ ] Select icon
- [ ] Export settings:
  - **Format:** SVG
  - **Scale:** 1x (vector)
- [ ] Name: `icon-name.svg`

For images:
- [ ] Export settings:
  - **Format:** PNG
  - **Scale:** 1x, 2x, 3x (for retina)

### Code Export
- [ ] Install plugin: **"Figma to Code"** or **"Anima"**
- [ ] Export key components as React/HTML
- [ ] Review generated code
- [ ] Share with development team

---

## ✅ Phase 10: Final Review (10 min)

### Quality Check
- [ ] All text uses text styles (no direct formatting)
- [ ] All colors use color styles (no raw hex)
- [ ] Components have descriptive names
- [ ] Frames are properly organized
- [ ] Auto-Layout is applied consistently
- [ ] Prototype flows work correctly

### Accessibility Check
- [ ] Color contrast meets WCAG AA (4.5:1 ratio)
- [ ] Touch targets ≥ 44×44px (mobile)
- [ ] Text is readable at all sizes
- [ ] Focus states visible on all interactive elements

### Performance Check
- [ ] Flatten unnecessary groups
- [ ] Remove hidden/unused layers
- [ ] Optimize complex vectors
- [ ] Check file size (<50MB ideal)

---

## 🎉 Completion Checklist

You're done when you can check all of these:

- [ ] ✅ All 6 mockups imported and organized
- [ ] ✅ Color styles created (30+ styles)
- [ ] ✅ Text styles created (10+ styles)
- [ ] ✅ Layout grids configured (12-col desktop, 4-col mobile, 8px baseline)
- [ ] ✅ Components created (buttons, inputs, cards, badges)
- [ ] ✅ Auto-Layout applied to containers
- [ ] ✅ Interactive prototype working
- [ ] ✅ File shared with team
- [ ] ✅ Ready for development handoff

**Estimated Total Time:** 2-3 hours

---

## 📞 Need Help?

**Stuck on a step?**
- Figma Help: https://help.figma.com
- Figma Community: https://forum.figma.com
- YouTube: Search "Figma [feature name] tutorial"

**Questions about the design?**
- Review: `../README.md`
- Component specs: `component-naming-guide.md`
- Handoff details: `handoff-specifications.md`
