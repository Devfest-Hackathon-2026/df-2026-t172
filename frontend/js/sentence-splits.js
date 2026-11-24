/** 分割の履歴はセッション内の文オブジェクトで追跡する。保存データには入れない。 */
function location(session, path) {
  const match = /^soap\.([SO])\[(\d+)\]$/u.exec(path);
  if (!match || session.disposed || session.isLocked() || session.status === "verifying") return null;
  const list = session.draft.soap[match[1]], index = Number(match[2]);
  return list[index] ? { part: match[1], list, index, item: list[index] } : null;
}

export function canSplitSentence(session, path) {
  const loc = location(session, path);
  return Boolean(loc && loc.list.length < 50 && session.action(path) !== "delete");
}

export function splitSentence(session, path, { firstText, secondText } = {}) {
  if (!canSplitSentence(session, path) || [firstText, secondText].some((value) =>
    typeof value !== "string" || !value.trim() || value.length > 5000)) return null;
  const { part, list, item } = location(session, path);
  const originalText = item.text, originalOrigin = item.added_by ?? "ai";
  session.setElement(path, firstText);
  if (originalOrigin === "ai") item.added_by = "ai";
  const childOrigin = originalOrigin === "ai" ? "ai" : session.originForAddedText(secondText);
  const child = { text: secondText, evidence: [...item.evidence], added_by: childOrigin, plan_id: null };
  const childPath = `soap.${part}[${list.length}]`;
  list.push(child);
  if (child.added_by === "nurse") session.addedElements.add(child);
  session.splits.set(child, { source: item, originalText, part });
  session.touch(childPath, { entail: child.added_by !== "nurse" });
  return childPath;
}

export function canUndoSentenceSplit(session, path) {
  const loc = location(session, path);
  if (!loc || session.action(path) === "delete") return false;
  const record = session.splits.get(loc.item);
  if (!record || !loc.list.includes(record.source)
    || session.splitEdits.has(record.source) || session.splitEdits.has(loc.item)) return false;
  if (session.action(`soap.${loc.part}[${loc.list.indexOf(record.source)}]`) === "delete") return false;
  let later = false;
  for (const [child, other] of session.splits) {
    if (child === loc.item) { later = true; continue; }
    if (!loc.list.includes(child)) continue;
    if (other.source === loc.item || (later && other.source === record.source)) return false;
  }
  return true;
}

export function undoSentenceSplit(session, path) {
  if (!canUndoSentenceSplit(session, path)) return false;
  const { part, list, index, item } = location(session, path);
  const { source, originalText } = session.splits.get(item);
  const sourcePath = `soap.${part}[${list.indexOf(source)}]`;
  session.setElement(sourcePath, originalText);
  const entail = source.added_by !== "nurse" || list.slice(index).some((sentence) => sentence.added_by !== "nurse");
  session.addedElements.delete(item);
  session.splits.delete(item);
  list.splice(index, 1);
  session.invalidateSentencePositions(`soap.${part}`, index);
  session.touch(sourcePath, { entail });
  return true;
}
