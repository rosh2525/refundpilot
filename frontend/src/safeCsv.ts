// Spreadsheet apps interpret these prefixes as executable formulas, even in quoted CSV cells.
// Apply to every exported value, including customer text and nested audit details.
export function safeCsvValue(value:unknown):string {
 const text=value==null?'':String(value);
 return /^(?:[\s\u0000-\u001f]*[=+\-@]|[\t\r\n])/.test(text)?"'"+text:text;
}
