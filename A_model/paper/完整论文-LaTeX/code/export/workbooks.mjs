import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {FileBlob,SpreadsheetFile} from '@oai/artifact-tool';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'results');
const preview=path.join(out,'previews');await fs.mkdir(preview,{recursive:true});
const mode=process.argv[2]??'export';
if(mode==='templates'){
  for(let q=1;q<=4;q++){
    const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'data','templates',`result${q}.xlsx`)));
    const sheet=wb.worksheets.getItemAt(0);
    const blob=await wb.render({sheetName:sheet.name,range:'A1:F5',scale:1.5,format:'png'});
    await fs.writeFile(path.join(preview,`template${q}.png`),new Uint8Array(await blob.arrayBuffer()));
  }
}else{
  const books=JSON.parse(await fs.readFile(path.join(out,'workbooks.json'),'utf8'));
  for(const book of books.filter(b=>!process.argv[3] || b.q===Number(process.argv[3]))){
    if(book.q===4){
      if(!book.source_sha256) throw new Error('Regenerate the Q4 payload with current model checks.');
      for(const [name,expected] of Object.entries(book.source_sha256)){
        const actual=createHash('sha256').update(await fs.readFile(path.join(out,name))).digest('hex');
        if(actual!==expected) throw new Error(`Stale Q4 payload: ${name} changed after preparation.`);
      }
      const meta=JSON.parse(await fs.readFile(path.join(out,'q4.json'),'utf8'));
      if(meta.model!==4 || meta.ale!==false || meta.moving!==true || meta.tail!=='mean')
        throw new Error('Q4 primary must use material coordinates and mean tail.');
    }
    const wb=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(root,'data','templates',`result${book.q}.xlsx`)));
    for(const spec of book.sheets){
      const sheet=wb.worksheets.getItem(spec.name),rows=spec.rows,cols=rows[0].length;
      sheet.getUsedRange().clear({applyTo:'contents'});
      sheet.getRangeByIndexes(0,0,rows.length,cols).values=rows;
      sheet.getRangeByIndexes(1,1,rows.length-1,cols-1).setNumberFormat('0.0000');
      sheet.getRangeByIndexes(0,1,1,cols-1).setNumberFormat('0.0');
      sheet.getRangeByIndexes(0,0,1,cols).format.font={name:'Microsoft YaHei',size:10,bold:true};
      sheet.getRangeByIndexes(0,0,1,cols).format.rowHeight=30;
      sheet.getRangeByIndexes(0,0,rows.length,1).format.columnWidth=33;
      sheet.getRangeByIndexes(0,1,rows.length,cols-1).format.columnWidth=12;
      sheet.freezePanes.freezeRows(1);
    }
    wb.recalculate();
    for(const spec of book.sheets){
      const blob=await wb.render({sheetName:spec.name,range:'A1:H8',scale:1.2,format:'png'});
      await fs.writeFile(path.join(preview,`result${book.q}_${spec.name}.png`),new Uint8Array(await blob.arrayBuffer()));
      if(book.q===4){
        const last=spec.rows.length;
        for(const [label,range] of [['end',`A${last-4}:F${last}`],['surface',`R${last-4}:W${last}`]]){
          const snapshot=await wb.render({sheetName:spec.name,range,scale:1.2,format:'png'});
          await fs.writeFile(path.join(preview,`result4_${label}.png`),new Uint8Array(await snapshot.arrayBuffer()));
        }
      }
      console.log((await wb.inspect({kind:'table',range:`'${spec.name}'!A1:D3`,include:'values',tableMaxRows:3,tableMaxCols:4,maxChars:600})).ndjson);
    }
    console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:5},maxChars:400})).ndjson);
    await (await SpreadsheetFile.exportXlsx(wb)).save(path.join(out,`result${book.q}.xlsx`));
    console.log(`Exported result${book.q}.xlsx`);
  }
}
