export function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function reviewButton(label, action, className = "secondary-button") {
  const button = element("button", className, label);
  button.type = "button";
  button.dataset.reviewAction = action;
  button.dataset.focusKey = `review-${action}`;
  return button;
}

export function panel(title) {
  const section = element("section", "review-panel");
  section.append(element("h2", "panel-heading", title));
  return section;
}
