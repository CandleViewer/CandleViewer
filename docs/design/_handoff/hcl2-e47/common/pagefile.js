// Read-only: the open file and current page as {name, id} pairs, in the exact out/page.txt form the return note quotes.
return {
  page: { name: penpot.currentPage.name, id: penpot.currentPage.id },
  file: { name: penpot.currentFile.name, id: penpot.currentFile.id },
};
