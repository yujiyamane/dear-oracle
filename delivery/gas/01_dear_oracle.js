// delivery/gas/01_dear_oracle.js — Dear Oracle GAS delivery adapter
// Separate GAS project (new scriptId, NOT dawn-patrol, NOT dear-keyperson).
// Read-only: doGet serves the stored letter HTML; no doPost.
// Letter generation (claude -p) runs on the PC via Task Scheduler BEFORE this fires.

var DRIVE_FOLDER_NAME = "dear-oracle-letters";


// ---------------------------------------------------------------------------
// doGet — serve the letter HTML for a given date
// ---------------------------------------------------------------------------

function doGet(e) {
  var params = e && e.parameter ? e.parameter : {};
  var today  = Utilities.formatDate(new Date(), "Australia/Sydney", "yyyy-MM-dd");
  var date   = params.date || today;

  try {
    var folder    = DriveApp.getFoldersByName(DRIVE_FOLDER_NAME).next();
    var files     = folder.getFilesByName(date + ".html");
    if (files.hasNext()) {
      var html = files.next().getBlob().getDataAsString("UTF-8");
      return HtmlService.createHtmlOutput(html)
        .setTitle("Dear Oracle — " + date);
    }
  } catch (err) {
    Logger.log("doGet error: " + err);
  }

  return HtmlService.createHtmlOutput(
    "<p>No letter for " + date + "</p>"
  ).setTitle("Dear Oracle — not found");
}


// ---------------------------------------------------------------------------
// sendDigest_ — email the 3-line digest + read-more link
// ---------------------------------------------------------------------------

function sendDigest_(date, digestText, recipientEmail) {
  var readMoreUrl = ScriptApp.getService().getUrl() + "?date=" + date;
  MailApp.sendEmail({
    to:      recipientEmail,
    subject: "Dear Oracle, " + date,
    body:    digestText + "\n\nRead the full letter: " + readMoreUrl,
  });
}


// ---------------------------------------------------------------------------
// installTriggers_ — delete all, install a daily 05:30 Sydney trigger
// ---------------------------------------------------------------------------

function installTriggers_() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    ScriptApp.deleteTrigger(t);
  });

  ScriptApp.newTrigger("runDaily_")
    .timeBased()
    .atHour(5)
    .nearMinute(30)
    .everyDays(1)
    .inTimezone("Australia/Sydney")
    .create();
}


// ---------------------------------------------------------------------------
// runDaily_ — read the day's .txt from Drive, email digest
// ---------------------------------------------------------------------------

function runDaily_(date) {
  var today = date || Utilities.formatDate(new Date(), "Australia/Sydney", "yyyy-MM-dd");

  var props         = PropertiesService.getScriptProperties();
  var recipientEmail = props.getProperty("RECIPIENT_EMAIL");
  if (!recipientEmail) {
    Logger.log("runDaily_: RECIPIENT_EMAIL not set in script properties");
    return;
  }

  try {
    var folder   = DriveApp.getFoldersByName(DRIVE_FOLDER_NAME).next();
    var txtFiles = folder.getFilesByName(today + ".txt");
    if (!txtFiles.hasNext()) {
      Logger.log("runDaily_: no .txt file for " + today);
      return;
    }

    var plaintext = txtFiles.next().getBlob().getDataAsString("UTF-8");
    var lines     = plaintext.split("\n").filter(function (l) { return l.trim() !== ""; });
    var digest    = lines.slice(0, 3).join("\n");

    sendDigest_(today, digest, recipientEmail);
  } catch (err) {
    Logger.log("runDaily_ error: " + err);
  }
}
