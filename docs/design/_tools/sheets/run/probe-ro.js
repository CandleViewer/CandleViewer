return {
  page: penpot.currentPage ? penpot.currentPage.name : null,
  pages: (penpot.currentFile ? penpot.currentFile.pages : []).length,
  cv: storage.cvd02 ? storage.cvd02.v : null,
  sheet: storage.cvsheet ? storage.cvsheet.v : null,
};
