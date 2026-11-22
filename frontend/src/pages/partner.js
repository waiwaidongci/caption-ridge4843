import {datasetField, feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {GRANULARITY} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

function requestBody(form) {
  const data = new FormData(form);
  return {dataset_id:Number(data.get('dataset_id')), granularity:data.get('granularity'),
    start:data.get('start') || '', end:data.get('end') || ''};
}

function exportGrid(snapshot) {
  return table([
    {key:'label',label:'日期段'},
    {key:'count',label:'工单数'},
    {label:'实耗分钟',render:row=>row.minutes === null ? pill('已隐藏','blocked') : value(row.minutes)},
    {label:'说明',render:row=>row.reason || '—'},
  ], [...snapshot.rows, snapshot.total], {caption:'导出表', pageSize:40});
}

function formPanel(message, previewBox, refresh) {
  const previewButton = button('预览出表',{type:'submit',class:'quiet','data-testid':'preview-export'});
  const publishButton = button('发布此表',{type:'button',class:'primary','data-testid':'publish-export'});
  const form = el('form',{class:'fields','data-testid':'export-form',onSubmit:handler(previewButton,message,async event=>{
    const result = await workspace.previewPublication(requestBody(event.target));
    previewBox.replaceChildren(
      result.publishable ? p('与已发表格联合校验通过，可以发布。','subtle')
        : p(`结合已发表的表可反推 ${result.conflict} 的实耗，当前配置无法发布。`,'feedback'),
      exportGrid(result.table));
  }})}, datasetField(workspace.datasets),
    el('label',{class:'field',for:'granularity'},el('span',{},'出表粒度'),
      el('select',{id:'granularity',name:'granularity'},
        Object.entries(GRANULARITY).map(([key,label])=>el('option',{value:key},label)))),
    el('div',{class:'form-grid'},
      field({key:'start',label:'起始日期（可空）',type:'date',required:false}),
      field({key:'end',label:'结束日期（可空）',type:'date',required:false})),
    el('div',{class:'actions'},previewButton, session.canWrite && publishButton));
  publishButton.addEventListener('click',handler(publishButton,message,async()=>{
    if (!form.reportValidity()) return;
    const result = await workspace.publish(requestBody(form));
    const target = `#partner/${result.id}`;
    if (location.hash === target) await refresh();
    else location.hash = target;
  }));
  return form;
}

export async function partnerPage(route, refresh) {
  const {spec, datasets} = workspace;
  const message = feedback();
  const previewBox = el('div',{class:'preview-box'});
  const items = await workspace.publications();
  const selected = route.id ? await workspace.getPublication(route.id) : null;
  const detail = selected && panel(`发布 #${selected.id} · ${GRANULARITY[selected.granularity]}`,
    p(`${selected.start || '最早'} 至 ${selected.end || '最晚'} · ${selected.order_count} 单 · 隐藏 ${selected.hidden_count} 格 · ${selected.author} 发布于 ${date(selected.created_at)}`,'subtle'),
    exportGrid(selected.table));
  const list = table([
    {label:'表',render:row=>link(`#${row.id} · ${GRANULARITY[row.granularity]}`,`#partner/${row.id}`)},
    {label:'日期范围',render:row=>`${row.start || '最早'} 至 ${row.end || '最晚'}`},
    {key:'order_count',label:'工单数'},
    {key:'hidden_count',label:'隐藏格'},
    {key:'author',label:'发布人'},
    {label:'时间',render:row=>date(row.created_at)},
    {label:'下载',render:row=>{
      const download = button('下载 CSV',{class:'quiet'});
      download.addEventListener('click',handler(download,message,() =>
        workspace.download(`/publications/${row.id}/download`,`partner-hours-${row.id}.csv`)));
      return download;
    }},
  ], items, {caption:'已发表格', empty:'尚未发布过合作方导出表。'});
  return el('div',{class:'two-col'},el('div',{class:'wide-panel'},detail,
    panel('出表与发布', datasets.length ? formPanel(message,previewBox,refresh) : empty('请先导入数据。','#inputs','前往导入'),
      message, previewBox),
    panel('已发表格',list)),
    el('aside',{class:'sidebar-panel'},panel('防反推口径',el('ul',{class:'method-list'},spec.export_rules.map(text=>el('li',{},text))))));
}
