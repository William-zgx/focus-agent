type TooltipAttributeBag = {
  "data-default-tooltip"?: string;
  "data-tooltip"?: string;
  title?: string;
};

function normalizeTooltipText(text?: string | null) {
  const trimmed = text?.trim();
  return trimmed ? trimmed : undefined;
}

export function tooltipProps(
  tooltip?: string | null,
  options: {
    defaultTooltip?: string | null;
  } = {},
): TooltipAttributeBag {
  const currentTooltip = normalizeTooltipText(tooltip);
  const defaultTooltip = normalizeTooltipText(options.defaultTooltip);
  const title = currentTooltip ?? defaultTooltip;

  return {
    ...(defaultTooltip ? { "data-default-tooltip": defaultTooltip } : {}),
    ...(currentTooltip ? { "data-tooltip": currentTooltip } : {}),
    ...(title ? { title } : {}),
  };
}

export function syncTooltipText(element: HTMLElement, tooltip?: string | null) {
  const currentTooltip = normalizeTooltipText(tooltip);
  const defaultTooltip = normalizeTooltipText(element.dataset.defaultTooltip);
  const title = currentTooltip ?? defaultTooltip;

  if (currentTooltip) {
    element.dataset.tooltip = currentTooltip;
  } else {
    delete element.dataset.tooltip;
  }

  if (title) {
    element.title = title;
  } else {
    element.removeAttribute("title");
  }
}
