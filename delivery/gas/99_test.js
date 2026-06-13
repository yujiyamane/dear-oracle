// delivery/gas/99_test.js — GAS unit tests for Dear Oracle delivery adapter

function runAllTests_() {
  testDoGetMissingFile_();
  testDoGetReturnsHtml_();
  Logger.log("All GAS tests passed.");
}


// testDoGetMissingFile_ — when no letter exists for a date, serve fallback page
function testDoGetMissingFile_() {
  var fakeDate = "1970-01-01";
  var result   = doGet({ parameter: { date: fakeDate } });
  var html     = result.getContent();

  if (html.indexOf("No letter for " + fakeDate) === -1) {
    throw new Error(
      "testDoGetMissingFile_ FAILED: expected 'No letter for " + fakeDate + "' in output.\nGot: " + html
    );
  }
  Logger.log("testDoGetMissingFile_ PASSED");
}


// testDoGetReturnsHtml_ — when a letter exists, its HTML content is served
function testDoGetReturnsHtml_() {
  // Create a temp file in the Drive folder, then clean up after
  var folderIter = DriveApp.getFoldersByName(DRIVE_FOLDER_NAME);
  if (!folderIter.hasNext()) {
    Logger.log("testDoGetReturnsHtml_ SKIPPED: Drive folder not found");
    return;
  }
  var folder   = folderIter.next();
  var testDate = "2000-01-01";
  var testHtml = "<p>test-content</p>";

  var file = folder.createFile(testDate + ".html", testHtml, MimeType.HTML);
  try {
    var result  = doGet({ parameter: { date: testDate } });
    var content = result.getContent();
    if (content.indexOf("test-content") === -1) {
      throw new Error("testDoGetReturnsHtml_ FAILED: expected test-content in output");
    }
    Logger.log("testDoGetReturnsHtml_ PASSED");
  } finally {
    file.setTrashed(true);
  }
}
