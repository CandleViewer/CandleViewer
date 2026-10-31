import type { Meta, StoryObj } from "@storybook/react-vite";
import type { CSSProperties, JSX, ReactNode } from "react";
import { expect, fn, waitFor, within } from "storybook/test";
import { Button } from "./Button.js";
import { Callout } from "./Callout.js";
import { DensityToggle, DensityToggleConnected } from "./DensityToggle.js";
import { ForbiddenState } from "./ForbiddenState.js";
import { GlobalErrorBoundaryFallback } from "./GlobalErrorBoundaryFallback.js";
import { IconButton } from "./IconButton.js";
import { NotFoundState } from "./NotFoundState.js";
import { PreviewTile } from "./PreviewTile.js";
import { RbacGate } from "./RbacGate.js";
import { SKIP_LINK_COPY, SkipLink } from "./SkipLink.js";
import { ThemeSwitcher, ThemeSwitcherConnected } from "./ThemeSwitcher.js";

/**
 * E05-S04's visual-regression matrix: every component of the story together, at rest. Theme and density are the
 * visual-regression cell's (`vr/matrix.ts` sends them as URL globals, which win over a story's own), so the six
 * named stories of the E05-S03 matrices would only repeat each other: two stories carry the motion axis instead.
 * `MotionReduce` pins `motion: "on"` and `MotionSafe` pins `"off"`; the capture reads the pin (`expectedMotion`).
 * Excluded: the density menu form is closed (its popup is portalled), no tooltip is open, no timer runs, and the
 * skip link is in its resting, clipped state.
 */
const meta: Meta = {
  title: "Molecules/E05-S04 theming matrix",
  parameters: { layout: "padded" },
};
export default meta;
type Story = StoryObj;

const grid: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(20rem, 1fr))",
  gap: "var(--space-inset-md)",
  color: "var(--color-text-primary)",
};

function Cell({
  title,
  children,
}: {
  readonly title: string;
  readonly children: ReactNode;
}): JSX.Element {
  return (
    <section
      aria-label={title}
      style={{ display: "grid", gap: "var(--space-inset-xs)", alignContent: "start" }}
    >
      <h2 style={{ fontSize: "inherit", margin: 0 }}>{title}</h2>
      {children}
    </section>
  );
}

/** Two token values read at run time (no raw colour in a story): a pair under the contrast floor. */
function LowContrastTile(): JSX.Element {
  const css = getComputedStyle(document.documentElement);
  const read = (name: string): string => css.getPropertyValue(name).trim();
  return (
    <PreviewTile
      kind="theme"
      label="Preview: low contrast sample"
      source="sample"
      tokenOverrides={{
        "color.text.primary": read("--color-border-strong"),
        "color.surface.sunken": read("--color-border-default"),
      }}
    />
  );
}

const noop = (): void => undefined;
const LADDER = ["63 118.5", "63 118.0", "12.4k", "8.1k", "+4.3k"];

function E05S04Matrix(): JSX.Element {
  return (
    <div style={grid}>
      <Cell title="Theme switcher">
        <ThemeSwitcherConnected />
        <ThemeSwitcher value="dark" matchSystem onChange={noop} onMatchSystemChange={noop} />
      </Cell>
      <Cell title="Density toggle">
        <DensityToggleConnected />
        <DensityToggle scope="panel" panelName="Order book" value="comfortable" onChange={noop} />
        <DensityToggleConnected form="menu" />
        <DensityToggle form="menu" value="compact" onChange={noop} />
      </Cell>
      <Cell title="Preview tiles">
        <PreviewTile kind="theme" label="Preview: theme sample" caption="Changes: this theme" />
        <PreviewTile kind="ladder" label="Preview: ladder, five figures" value={LADDER} />
        <LowContrastTile />
        <PreviewTile kind="chart" label="Preview: chart" status="empty" />
      </Cell>
      <Cell title="RBAC gate">
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
          <Button>Save layout</Button>
        </RbacGate>
        <RbacGate
          form="tooltip"
          allowed={false}
          reason="rbac.owner_only"
          fills={{ verb: "change settings" }}
        >
          <IconButton icon="settings" label="Account settings" />
        </RbacGate>
        <Callout id="matrix-notice" title="Only the owner can change settings." live="off" />
        <RbacGate
          form="notice"
          noticeId="matrix-notice"
          allowed={false}
          reason="rbac.owner_only"
          fills={{ verb: "change settings" }}
        >
          <Button>Rename account</Button>
        </RbacGate>
      </Cell>
      <Cell title="Skip link">
        <SkipLink targets={[{ id: "matrix-main", label: SKIP_LINK_COPY.main }]} />
        <main id="matrix-main">Main content</main>
      </Cell>
      <Cell title="Forbidden state">
        <ForbiddenState
          scope="permission"
          capability="see the journal"
          homeHref="/"
          refId="req-1"
        />
      </Cell>
      <Cell title="Not found state">
        <NotFoundState path="/nowhere" tryRoutes={[{ label: "Charts", href: "/charts" }]} />
      </Cell>
      <Cell title="Error fallback">
        <GlobalErrorBoundaryFallback
          scope="panel"
          correlationId="err-0001"
          onReload={fn()}
          onRemovePanel={fn()}
          onCopyDiagnostics={() => Promise.resolve()}
        />
        <GlobalErrorBoundaryFallback
          scope="route"
          correlationId="err-0002"
          onReload={fn()}
          onReloadApp={fn()}
          onCopyDiagnostics={() => Promise.resolve()}
        />
      </Cell>
    </div>
  );
}

const played =
  (motion: "reduce" | "safe") =>
  async ({ canvasElement }: { canvasElement: HTMLElement }): Promise<void> => {
    const root = document.documentElement;
    const ui = within(canvasElement);
    await waitFor(() => expect(root).toHaveAttribute("data-motion", motion));
    // Under the storybook gate the toolbar cell is dark / compact; the VR cells set the others.
    await expect(root.dataset["theme"]).toMatch(/^(dark|light|high-contrast)$/);
    await expect(root.dataset["density"]).toMatch(/^(compact|comfortable)$/);
    await expect(ui.getAllByRole("radiogroup", { name: "Theme" }).length).toBeGreaterThan(0);
    await expect(ui.getAllByRole("radiogroup", { name: "Density" }).length).toBeGreaterThan(0);
    await expect(ui.getByRole("button", { name: /^Density: / })).toBeVisible();
    await expect(ui.getAllByRole("img", { name: /^Preview/ }).length).toBeGreaterThanOrEqual(3);
    await expect(ui.getByRole("button", { name: "Save layout" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(ui.getByRole("button", { name: "Account settings" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await expect(ui.getByRole("link", { name: SKIP_LINK_COPY.main })).toBeInTheDocument();
    await expect(ui.getAllByRole("heading", { level: 1 }).length).toBeGreaterThanOrEqual(3);
    await expect(
      ui.getAllByRole("alert").length + ui.getAllByRole("region").length,
    ).toBeGreaterThan(0);
    // Every portalled menu is closed at rest.
    await expect(document.querySelector('[role="menu"]:not([hidden])')).toBeNull();
    await expect(document.querySelector('[role="listbox"]')).toBeNull();
  };

export const MotionReduce: Story = {
  globals: { motion: "on" },
  render: () => <E05S04Matrix />,
  play: played("reduce"),
};

export const MotionSafe: Story = {
  globals: { motion: "off" },
  render: () => <E05S04Matrix />,
  play: played("safe"),
};
