# Component Naming Guide

Consistent naming conventions for Figma components, variants, and design tokens.

---

## 🎯 Naming Philosophy

**Principles:**
1. **Hierarchical** - Use `/` to create categories
2. **Descriptive** - Name should explain purpose
3. **Consistent** - Same pattern across all components
4. **Searchable** - Easy to find in component panel

**Format:**
```
Category/Component/Variant/State
```

**Examples:**
- `Button/Primary/Default`
- `Input/Text/Focused`
- `Card/Entity/Default`

---

## 📦 Component Categories

### Buttons
```
Button/
├── Primary/
│   ├── Default
│   ├── Hover
│   ├── Active
│   ├── Disabled
│   └── Loading
├── Secondary/
│   ├── Default
│   ├── Hover
│   └── Disabled
├── Destructive/
│   ├── Default
│   ├── Hover
│   └── Disabled
└── Ghost/
    ├── Default
    ├── Hover
    └── Disabled
```

**Variant Properties:**
- `State`: Default, Hover, Active, Disabled, Loading
- `Size`: Small, Medium, Large (if applicable)
- `Icon`: None, Left, Right (if applicable)

---

### Form Inputs
```
Input/
├── Text/
│   ├── Default
│   ├── Focused
│   ├── Error
│   ├── Disabled
│   └── Success
├── Textarea/
│   ├── Default
│   ├── Focused
│   └── Error
├── Select/
│   ├── Default
│   ├── Open
│   └── Disabled
├── Checkbox/
│   ├── Unchecked
│   ├── Checked
│   └── Indeterminate
└── Radio/
    ├── Unselected
    └── Selected
```

**Variant Properties:**
- `State`: Default, Focused, Error, Disabled, Success
- `Size`: Small, Medium, Large
- `Has Label`: True, False

---

### Cards
```
Card/
├── Entity/
│   ├── Default
│   ├── Hover
│   └── Selected
├── Memory/
│   ├── Default
│   ├── Hover
│   └── Selected
├── Stats/
│   └── Default
└── Upload/
    ├── Success
    ├── Processing
    └── Error
```

**Variant Properties:**
- `State`: Default, Hover, Selected, Disabled
- `Domain`: Work, Family, Personal, Logistics (for entity cards)
- `Type`: Person, Company, Project, Document (for entity cards)

---

### Badges & Pills
```
Badge/
├── Domain/
│   ├── Work
│   ├── Family
│   ├── Personal
│   └── Logistics
├── Tag/
│   ├── Default
│   └── Removable
├── Importance/
│   ├── High (80-100%)
│   ├── Medium (60-79%)
│   └── Low (40-59%)
└── Status/
    ├── Active
    ├── Pending
    └── Archived
```

**Variant Properties:**
- `Domain`: Work, Family, Personal, Logistics
- `Removable`: True, False (for tags)
- `Level`: High, Medium, Low (for importance)

---

### Modals & Overlays
```
Modal/
├── Entity Form/
│   ├── Create
│   └── Edit
├── Confirmation/
│   ├── Default
│   ├── Destructive
│   └── Success
└── Detail View/
    ├── Entity
    └── Memory
```

**Variant Properties:**
- `Type`: Create, Edit, Delete, Confirm
- `Size`: Small, Medium, Large, Full

---

### Navigation
```
Nav/
├── Tab Item/
│   ├── Inactive
│   ├── Active
│   └── Hover
├── Breadcrumb/
│   ├── Default
│   └── Current
└── Pagination/
    ├── Number
    ├── Previous
    └── Next
```

**Variant Properties:**
- `State`: Inactive, Active, Hover, Disabled
- `Icon`: True, False

---

### Feedback
```
Feedback/
├── Toast/
│   ├── Success
│   ├── Error
│   ├── Warning
│   └── Info
├── Alert/
│   ├── Info
│   ├── Warning
│   └── Error
└── Progress/
    ├── Determinate
    └── Indeterminate
```

**Variant Properties:**
- `Type`: Success, Error, Warning, Info
- `Dismissible`: True, False
- `Icon`: True, False

---

## 🎨 Design Token Naming

### Colors
```
Color/
├── Primary/
│   ├── Blue-50
│   ├── Blue-600
│   └── Blue-700
├── Gray/
│   ├── 50 through 900
├── Semantic/
│   ├── Success
│   ├── Error
│   ├── Warning
│   └── Info
└── Domain/
    ├── Work
    ├── Family
    ├── Personal
    └── Logistics
```

**Format:** `Color/Category/Name` or `Color/Category/Shade`

---

### Typography
```
Text/
├── Heading/
│   ├── H1
│   ├── H2
│   ├── H3
│   └── H4
├── Body/
│   ├── Large
│   ├── Default
│   └── Small
└── Special/
    ├── Label
    ├── Button
    ├── Code
    └── Caption
```

**Format:** `Text/Category/Size`

---

### Spacing
```
Spacing/
├── 1 (4px)
├── 2 (8px)
├── 3 (12px)
├── 4 (16px)
├── 6 (24px)
├── 8 (32px)
└── 12 (48px)
```

**Format:** `Spacing/Number` or use direct values in Auto-Layout

---

## 📏 Naming Best Practices

### ✅ DO

**Use descriptive names:**
```
✅ Button/Primary/Hover
✅ Input/Text/Error
✅ Card/Entity/Selected
```

**Use hierarchy:**
```
✅ Nav/Tab Item/Active
✅ Badge/Domain/Work
```

**Be specific:**
```
✅ Modal/Entity Form/Create
✅ Toast/Success/Dismissible
```

**Use consistent naming:**
```
✅ All buttons use "Hover" state
✅ All inputs use "Focused" state
```

---

### ❌ DON'T

**Don't use abbreviations:**
```
❌ Btn/Pri/Hvr
✅ Button/Primary/Hover
```

**Don't use generic names:**
```
❌ Component 1
❌ Card Copy
✅ Card/Entity/Default
```

**Don't use colors in names (unless describing color):**
```
❌ Button/Blue
✅ Button/Primary
```

**Don't inconsistent naming:**
```
❌ Some use "Hover", others use "Hovered"
✅ All use "Hover"
```

---

## 🔄 Variant Property Names

### State Properties
```javascript
State: "Default" | "Hover" | "Active" | "Focused" | "Disabled" | "Loading" | "Error" | "Success"
```

### Size Properties
```javascript
Size: "Small" | "Medium" | "Large"
```

### Domain Properties
```javascript
Domain: "Work" | "Family" | "Personal" | "Logistics"
```

### Type Properties (Entities)
```javascript
Type: "Person" | "Company" | "Project" | "Document" | "Event"
```

### Boolean Properties
```javascript
Has Icon: "True" | "False"
Removable: "True" | "False"
Dismissible: "True" | "False"
```

---

## 🏷️ Layer Naming in Components

### Structure
```
Component Name
├── .background (frame/rectangle)
├── .content (auto-layout frame)
│   ├── .icon (optional)
│   ├── .label (text)
│   └── .badge (optional)
├── .border (optional)
└── .overlay (for states)
```

### Prefix Conventions
- `.` prefix = internal layer (e.g., `.background`)
- `_` prefix = hidden/structural (e.g., `_spacing`)
- No prefix = exposed property

**Example: Button Component**
```
Button/Primary
├── .background (auto-layout frame)
├── .content (auto-layout frame)
│   ├── icon (instance, exposed)
│   └── label (text, exposed)
└── .state-overlay (for hover/active)
```

---

## 📋 Quick Reference Cheatsheet

| Component | Format | Example |
|-----------|--------|---------|
| **Buttons** | `Button/[Type]/[State]` | `Button/Primary/Hover` |
| **Inputs** | `Input/[Type]/[State]` | `Input/Text/Focused` |
| **Cards** | `Card/[Type]/[State]` | `Card/Entity/Selected` |
| **Badges** | `Badge/[Category]/[Variant]` | `Badge/Domain/Work` |
| **Modals** | `Modal/[Purpose]/[Type]` | `Modal/Entity Form/Create` |
| **Colors** | `Color/[Category]/[Name]` | `Color/Primary/Blue-600` |
| **Text** | `Text/[Category]/[Size]` | `Text/Heading/H2` |
| **Spacing** | `Spacing/[Number]` | `Spacing/4` (16px) |

---

## 🔍 Finding Components

### In Figma Assets Panel
1. Type search query
2. Use category filters
3. Sort by: Recently used / Alphabetical

### Search Examples
```
"button" → Shows all button variants
"primary" → Shows all primary components
"work" → Shows all work domain badges
"error" → Shows error states across all components
```

---

## 📦 Exporting Components

### For Developers
When exporting, maintain naming:

**React/TypeScript:**
```tsx
// Component name: Button/Primary/Default
export const ButtonPrimary = () => { ... }

// Component name: Card/Entity/Default
export const CardEntity = () => { ... }
```

**CSS Classes:**
```css
/* Component: Button/Primary/Hover */
.button-primary:hover { ... }

/* Component: Badge/Domain/Work */
.badge-domain-work { ... }
```

---

## ✅ Naming Checklist

Before publishing components, verify:

- [ ] Name follows `Category/Component/Variant` format
- [ ] No abbreviations used
- [ ] Variant properties are consistent
- [ ] Internal layers use `.` prefix
- [ ] Searchable keywords included
- [ ] No duplicate names
- [ ] Documentation added to description
- [ ] Matches design token names (for colors/text)

---

## 📚 Additional Resources

- [Figma Component Documentation](https://help.figma.com/hc/en-us/articles/360038662654)
- [Naming Conventions Best Practices](https://www.figma.com/best-practices/component-organization/)
- [Design Token Specification](https://design-tokens.github.io/community-group/)

---

**Questions?**
Review the main README or component specifications for more details.
