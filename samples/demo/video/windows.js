// In-page look-alikes of the desktop windows a screen recording would show: the
// document opened in its own program (to look through it before uploading) and the
// operating system's Open dialog.  A headless browser cannot film the real ones.
module.exports.STYLE = `
:host { all: initial; }
* { box-sizing: border-box; }
.wrap { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center;
  font-family: "Segoe UI", "Liberation Sans", "DejaVu Sans", Arial, sans-serif; font-size: 13px; color: #1b1b1b;
  line-height: 1.35; }
.wrap.win { background: rgba(0,0,0,.35); }
.wrap.dlg { background: rgba(0,0,0,.28); }
.__show { animation: __in .18s ease-out; }
@keyframes __in { from { opacity: 0; transform: scale(.985); } to { opacity: 1; transform: none; } }
.__w { width: 1480px; height: 960px; background: #fff; border-radius: 9px; overflow: hidden; display: flex;
  flex-direction: column; box-shadow: 0 24px 70px rgba(0,0,0,.55); color: #1b1b1b; font-size: 13px; }
.__tb { height: 36px; display: flex; align-items: center; background: #f3f3f3; color: #1b1b1b; flex: none; }
.__tb .ico { width: 18px; height: 18px; border-radius: 4px; margin: 0 10px 0 12px; display: grid; place-items: center;
  color: #fff; font: 700 10px/1 Arial; }
.__tb .t { flex: 1; font-size: 12.5px; }
.__tb .b { width: 46px; height: 36px; display: grid; place-items: center; font-size: 15px; color: #333; }
.__tb .x:hover, .__tb .x.hot { background: #c42b1c; color: #fff; }
.__rib { height: 40px; display: flex; align-items: center; gap: 22px; padding: 0 18px; color: #fff; font-size: 13px; flex: none; }
.__rib span.on { border-bottom: 2px solid #fff; padding-bottom: 6px; margin-top: 8px; }
.__tool { height: 40px; display: flex; align-items: center; gap: 18px; padding: 0 16px; background: #323639; color: #e8eaed;
  font-size: 13px; flex: none; }
.__tool .pg { background: #191b1c; padding: 3px 10px; border-radius: 3px; }
.__body { flex: 1; overflow-y: auto; overflow-x: hidden; scroll-behavior: auto; }
.__body.pdf { background: #525659; padding: 26px 0 40px; }
.__body.word { background: #e6e6e6; padding: 24px 0 40px; }
.__body.photo { background: #1f1f1f; display: flex; justify-content: center; padding: 20px 0; }
.__body.mail { background: #fafafa; }
.__body.xls { background: #fff; }
.__page { display: block; margin: 0 auto; width: 940px; box-shadow: 0 2px 10px rgba(0,0,0,.45); background: #fff; }
.__body.photo img { width: auto; max-width: 1100px; height: auto; display: block; }
.__body.photo.tall img { width: 880px; }
.mail { max-width: 980px; margin: 0 auto; padding: 30px 40px 60px; }
.mail .subj { font-size: 24px; font-weight: 600; margin-bottom: 18px; }
.mail .from { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 22px; font-size: 14px; }
.mail .avatar { width: 40px; height: 40px; border-radius: 50%; background: #0f6cbd; color: #fff; display: grid;
  place-items: center; font-weight: 700; font-size: 18px; flex: none; }
.mail .to { color: #616161; font-size: 13px; margin-top: 3px; }
.mail pre.body { font: 15px/1.6 "Segoe UI", "Liberation Sans", Arial, sans-serif; white-space: pre-wrap; margin: 0; }
.xl .xlbar { height: 32px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #d4d4d4; padding: 0 8px;
  font-size: 13px; position: sticky; top: 0; background: #fff; }
.xl .cellref { width: 80px; border: 1px solid #d4d4d4; padding: 2px 6px; }
.xl .fx { color: #777; font-style: italic; }
.xl table.grid { border-collapse: collapse; font: 14px Calibri, "Carlito", "Liberation Sans", Arial; }
.xl .grid th { background: #f3f3f3; color: #444; font-weight: 400; border: 1px solid #d4d4d4; height: 22px; font-size: 12px; }
.xl .grid th.rn { width: 42px; }
.xl .grid td { border: 1px solid #e1e1e1; height: 24px; padding: 0 6px; white-space: nowrap; }
.xl .grid td.b { font-weight: 700; }
.xl .grid td.num { text-align: right; }
.xl .tabs { position: sticky; bottom: 0; background: #f3f3f3; border-top: 1px solid #d4d4d4; height: 30px; display: flex;
  align-items: center; gap: 4px; padding-left: 40px; font-size: 13px; }
.xl .tab.on { background: #fff; color: #107c41; font-weight: 600; padding: 5px 16px; border-bottom: 2px solid #107c41; }
.xl .plus { color: #555; padding: 0 10px; }
/* the Open dialog */
.__d { width: 1360px; height: 800px; background: #fff; border-radius: 9px; overflow: hidden; display: flex; flex-direction: column;
  box-shadow: 0 24px 70px rgba(0,0,0,.5); color: #1b1b1b; font-size: 13px; }
.__d .bar { height: 46px; display: flex; align-items: center; gap: 10px; padding: 0 10px; background: #f9f9f9;
  border-bottom: 1px solid #e5e5e5; flex: none; }
.__d .nav-b { width: 28px; text-align: center; color: #555; font-size: 16px; }
.__d .addr { flex: 1; height: 30px; border: 1px solid #d9d9d9; border-radius: 4px; display: flex; align-items: center;
  gap: 4px; padding: 0 8px; background: #fff; }
.__d .crumb { padding: 3px 6px; border-radius: 3px; }
.__d .crumb.hot { background: #e5f1fb; }
.__d .sep { color: #888; }
.__d .search { width: 240px; height: 30px; border: 1px solid #d9d9d9; border-radius: 4px; display: flex; align-items: center;
  padding: 0 10px; color: #777; background: #fff; }
.__d .main { flex: 1; display: flex; min-height: 0; }
.__d .side { width: 210px; border-right: 1px solid #ececec; padding: 10px 6px; flex: none; }
.__d .side div { padding: 6px 12px; border-radius: 4px; color: #333; }
.__d .side div.on { background: #e5f1fb; }
.__d .side hr { border: none; border-top: 1px solid #ececec; margin: 6px 0; }
.__d .list { flex: 1; overflow: auto; }
.__d .hdr, .__d .row { display: grid; grid-template-columns: 250px 135px 185px 62px; align-items: center; padding: 0 14px; }
.__d .hdr { height: 32px; color: #555; border-bottom: 1px solid #ececec; }
.__d .hdr span:last-child, .__d .row span:last-child { text-align: right; }
.__d .row { height: 30px; border-radius: 4px; margin: 1px 6px; }
.__d .row.hot { background: #f0f6fd; }
.__d .row.sel { background: #cce8ff; }
.__d .row .nm { display: flex; align-items: center; gap: 9px; overflow: hidden; white-space: nowrap; }
.__d .row span { color: #444; }
.__d .row .nm { color: #1b1b1b; }
.__d .fi { width: 18px; height: 20px; border-radius: 2px; display: grid; place-items: center; color: #fff;
  font: 700 7px/1 Arial; flex: none; }
.__d .prev { width: 420px; border-left: 1px solid #ececec; background: #f7f7f7; display: flex; align-items: flex-start;
  justify-content: center; padding: 18px; overflow: hidden; flex: none; color: #777; }
.__d .prev img { max-width: 100%; max-height: 100%; box-shadow: 0 1px 6px rgba(0,0,0,.25); background: #fff; }
.__d .prev .mini { transform: scale(.42); transform-origin: top center; width: 940px; background: #fff;
  box-shadow: 0 1px 6px rgba(0,0,0,.25); }
.__d .foot { height: 66px; border-top: 1px solid #e5e5e5; display: flex; align-items: center; gap: 12px; padding: 0 16px;
  background: #f3f3f3; flex: none; }
.__d .fname { flex: 1; height: 30px; border: 1px solid #bdbdbd; border-bottom: 2px solid #0067c0; border-radius: 4px;
  background: #fff; display: flex; align-items: center; padding: 0 8px; }
.__d .ftype { width: 300px; height: 30px; border: 1px solid #d0d0d0; border-radius: 4px; background: #fff; display: flex;
  align-items: center; padding: 0 8px; color: #333; }
.__d .btn { width: 110px; height: 32px; border-radius: 4px; display: grid; place-items: center; border: 1px solid #d0d0d0;
  background: #fff; }
.__d .btn.open { background: #0067c0; color: #fff; border-color: #0067c0; }
.__d .btn.open.hot { background: #1975c5; }
`;

module.exports.ICON = {
  'PDF Document': ['#d93025', 'PDF'], 'JPG File': ['#2b88d8', 'JPG'], 'PNG File': ['#2b88d8', 'PNG'],
  'Microsoft Word Document': ['#185abd', 'W'], 'Microsoft Excel Worksheet': ['#107c41', 'X'],
  'Email Message': ['#0f6cbd', '✉'], 'File folder': ['#e8b130', ''],
};

// the program each kind of file opens in
module.exports.APP = {
  'PDF Document': { title: 'PDF Reader', color: '#d93025', kind: 'pdf' },
  'JPG File': { title: 'Photos', color: '#2b88d8', kind: 'photo' },
  'PNG File': { title: 'Photos', color: '#2b88d8', kind: 'photo' },
  'Microsoft Word Document': { title: 'Word', color: '#185abd', kind: 'word',
    ribbon: ['File', 'Home', 'Insert', 'Draw', 'Design', 'Layout', 'References', 'Mailings', 'Review', 'View'] },
  'Microsoft Excel Worksheet': { title: 'Excel', color: '#107c41', kind: 'xls',
    ribbon: ['File', 'Home', 'Insert', 'Page Layout', 'Formulas', 'Data', 'Review', 'View'] },
  'Email Message': { title: 'Mail', color: '#0f6cbd', kind: 'mail', ribbon: ['Reply', 'Reply all', 'Forward', 'Archive', 'Delete'] },
};
