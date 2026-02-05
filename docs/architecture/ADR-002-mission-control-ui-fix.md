# ADR-002: Mission Control UI Text Visibility Fix

## Status
Proposed

## Context
The Mission Control dispatch form contains a "Target Repository" dropdown field where the text options are not visible to human eyes, despite the functionality working correctly. This is a critical UI/UX issue that affects user experience and accessibility.

## Problem
- Target Repository dropdown text is unreadable (likely invisible or very low contrast)
- Other dropdown fields in the same form display text correctly
- Functionality works (options are selectable) but visibility is broken
- This affects user productivity and accessibility compliance

## Investigation Findings
During the initial investigation, the Mission Control component was not found in expected locations:
- `/src/app/dashboard/mission-control/page.tsx` - Not found
- `/src/components/MissionControl.tsx` - Not found
- `/src/components/DispatchForm.tsx` - Not found

## Technical Context
The project uses:
- Next.js 15+ with App Router
- Tailwind CSS for styling
- Dark/Light theme system via `next-themes`
- CSS custom properties for theme variables

## Root Cause Analysis
Based on the styling system, potential causes include:

1. **Missing Text Color Class**: Dropdown options missing `text-foreground` or similar Tailwind classes
2. **Theme Variable Issue**: CSS custom properties not being applied correctly
3. **Z-index/Overlay Issue**: Text being rendered behind other elements
4. **Contrast Issue**: Text color matching background color in certain themes

## Solution Architecture

### 1. Component Location Strategy
```bash
# Search patterns to locate Mission Control component
find src/ -name "*.tsx" -o -name "*.ts" | xargs grep -l "Target Repository"
find src/ -name "*.tsx" -o -name "*.ts" | xargs grep -l "dispatch"
find src/ -name "*.tsx" -o -name "*.ts" | xargs grep -l "Mission Control"
```

### 2. Dropdown Styling Standards
All dropdowns should follow this pattern:
```tsx
<select className=\"
  w-full px-3 py-2 
  bg-background 
  text-foreground 
  border border-border 
  rounded-md 
  focus:ring-2 focus:ring-primary 
  focus:border-transparent
  dark:bg-card 
  dark:text-card-foreground
\">
  <option value=\"\" className=\"text-foreground dark:text-card-foreground\">
    Select Repository
  </option>
  <option value=\"repo1\" className=\"text-foreground dark:text-card-foreground\">
    Repository 1
  </option>
</select>
```

### 3. CSS Custom Properties Usage
Ensure proper theme variable usage:
```css
/* Correct approach using CSS variables */
.dropdown-option {
  color: var(--foreground);
  background-color: var(--background);
}

/* Dark theme handling */
.dark .dropdown-option {
  color: var(--card-foreground);
  background-color: var(--card);
}
```

## Implementation Plan

### Phase 1: Discovery (1-2 hours)
1. Locate Mission Control dispatch form component
2. Identify current dropdown implementation
3. Document existing styling approach

### Phase 2: Analysis (30 minutes)
1. Compare working dropdowns vs broken dropdown
2. Identify specific styling differences
3. Test in both light and dark themes

### Phase 3: Fix Implementation (1 hour)
1. Apply consistent text color classes
2. Ensure theme compatibility
3. Add proper contrast ratios

### Phase 4: Testing (30 minutes)
1. Visual regression testing
2. Accessibility contrast testing (WCAG AA compliance)
3. Cross-theme functionality testing

## Acceptance Criteria
- [ ] Target Repository dropdown text is clearly visible
- [ ] Text contrast meets WCAG AA standards (4.5:1 ratio minimum)
- [ ] Styling consistent with other form dropdowns
- [ ] Works correctly in both light and dark themes
- [ ] No functional regressions introduced
- [ ] Dropdown remains fully functional (selection works)

## Testing Strategy
```typescript
// Visual regression test
describe('Mission Control Dispatch Form', () => {
  it('should display readable text in Target Repository dropdown', () => {
    // Test implementation
  });
  
  it('should maintain consistent styling across all dropdowns', () => {
    // Test implementation
  });
  
  it('should meet accessibility contrast requirements', () => {
    // Test implementation
  });
});
```

## Rollback Plan
If issues arise:
1. Revert to previous component state
2. Apply minimal text color fix as temporary solution
3. Schedule comprehensive form redesign if needed

## Monitoring
- Monitor user feedback post-fix
- Track form completion rates
- Verify no accessibility regressions

## Decision
**Approved** - Proceed with investigation and fix implementation following the outlined plan.

## Consequences
- Improved user experience and accessibility
- Consistent UI/UX across form elements  
- Better compliance with accessibility standards
- Reduced user confusion and support requests