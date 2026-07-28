const form = document.querySelector('#tripForm')
const homeView = document.querySelector('#homeView')
const resultView = document.querySelector('#resultView')
const loadingContainer = document.querySelector('#loadingContainer')
const loadingStatus = document.querySelector('#loadingStatus')
const progressBar = document.querySelector('#progressBar')
const progressTrack = document.querySelector('#progressTrack')
const errorBox = document.querySelector('#errorBox')
const submitText = document.querySelector('#submitText')
const daysAccordion = document.querySelector('#daysAccordion')
const mapState = document.querySelector('#mapState')

const agentNames = ['景点搜索 Agent', '天气查询 Agent', '酒店推荐 Agent', '行程规划 Agent']
const attractionImages = new Map()

let currentPlan = null
let originalPlan = null
let activeDayIndex = 0
let editMode = false
let loadingTimer = null
let loadingProgress = 0
let amapApiPromise = null
let amapMap = null

const escapeHtml = (value = '') => String(value).replace(/[&<>'"]/g, (character) => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  "'": '&#39;',
  '"': '&quot;'
})[character])

const money = (value = 0) => `¥${Number(value || 0).toLocaleString('zh-CN', {
  maximumFractionDigits: 0
})}`

const formatDate = (value) => new Intl.DateTimeFormat('zh-CN', {
  month: 'long',
  day: 'numeric',
  weekday: 'short'
}).format(new Date(`${value}T00:00:00`))

function hasCompleteMapCoordinates(plan) {
  const attractions = plan?.days?.flatMap((day) => day.attractions || []) || []
  return attractions.length > 0 && attractions.every((place) => (
    Number.isFinite(Number(place.location?.longitude)) &&
    Number.isFinite(Number(place.location?.latitude))
  ))
}

function initializeDates() {
  const start = new Date()
  start.setDate(start.getDate() + 7)
  const end = new Date(start)
  end.setDate(end.getDate() + 2)
  form.elements.start_date.value = start.toISOString().slice(0, 10)
  form.elements.end_date.value = end.toISOString().slice(0, 10)
  updateTravelDays()
}

function updateTravelDays() {
  const start = form.elements.start_date.value
  const end = form.elements.end_date.value
  const output = document.querySelector('#travelDays b')
  if (!start || !end) {
    output.textContent = '1'
    return 1
  }
  const days = Math.round(
    (new Date(`${end}T00:00:00`) - new Date(`${start}T00:00:00`)) / 86400000
  ) + 1
  form.elements.end_date.setCustomValidity(
    days < 1 ? '结束日期不能早于开始日期' : days > 30 ? '旅行天数不能超过30天' : ''
  )
  output.textContent = String(Math.max(1, Math.min(30, days)))
  return days
}

function requestFromForm() {
  const data = new FormData(form)
  return {
    city: data.get('city').trim(),
    start_date: data.get('start_date'),
    end_date: data.get('end_date'),
    travel_days: updateTravelDays(),
    transportation: data.get('transportation'),
    accommodation: data.get('accommodation'),
    preferences: data.getAll('preferences'),
    free_text_input: data.get('free_text_input').trim()
  }
}

function startLoading() {
  const statuses = [
    '📍 正在搜索景点…',
    '🌤️ 正在查询天气…',
    '🏨 正在推荐酒店…',
    '📋 正在生成行程计划…'
  ]
  loadingProgress = 5
  progressBar.style.width = `${loadingProgress}%`
  loadingStatus.textContent = '正在初始化 LangGraph 多 Agent…'
  loadingContainer.classList.remove('hidden')
  errorBox.classList.add('hidden')
  progressTrack.innerHTML = agentNames.map((name) => `<span>${escapeHtml(name)}</span>`).join('')
  loadingTimer = window.setInterval(() => {
    if (loadingProgress >= 90) return
    loadingProgress = Math.min(90, loadingProgress + 9)
    progressBar.style.width = `${loadingProgress}%`
    const index = Math.min(statuses.length - 1, Math.floor(loadingProgress / 23))
    loadingStatus.textContent = statuses[index]
  }, 600)
}

function stopLoading(success) {
  if (loadingTimer) window.clearInterval(loadingTimer)
  loadingTimer = null
  if (success) {
    progressBar.style.width = '100%'
    loadingStatus.textContent = '✅ 旅行计划生成完成！'
  }
}

form.addEventListener('submit', async (event) => {
  event.preventDefault()
  if (!form.reportValidity()) return
  const submitButton = form.querySelector('button[type="submit"]')
  submitButton.disabled = true
  submitText.textContent = '正在生成中…'
  startLoading()
  try {
    const response = await fetch('/api/trip/plan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestFromForm())
    })
    const payload = await response.json()
    if (!response.ok) throw new Error(payload.detail || '生成旅行计划失败')
    if (!payload.success || !payload.data) throw new Error(payload.message || '没有收到旅行计划数据')
    stopLoading(true)
    renderResult(payload.data)
  } catch (error) {
    stopLoading(false)
    errorBox.textContent = error.message
    errorBox.classList.remove('hidden')
  } finally {
    submitButton.disabled = false
    submitText.textContent = '🚀 开始规划我的旅行'
  }
})

function renderResult(plan) {
  currentPlan = structuredClone(plan)
  activeDayIndex = 0
  sessionStorage.setItem('tripPlan', JSON.stringify(currentPlan))
  homeView.classList.add('hidden')
  resultView.classList.remove('hidden')
  loadingContainer.classList.add('hidden')
  document.querySelector('#resultTitle').textContent = `${currentPlan.city}旅行计划`
  document.querySelector('#overviewContent').innerHTML = `
    <div class="overview-row">
      <strong>📅 日期：</strong>
      <span>${escapeHtml(currentPlan.start_date)} 至 ${escapeHtml(currentPlan.end_date)}</span>
    </div>
    <div class="overview-row">
      <strong>💡 建议：</strong>
      <span>${escapeHtml(currentPlan.overall_suggestions)}</span>
    </div>`
  document.querySelector('#budgetPanel').innerHTML = renderBudget(currentPlan.budget)
  renderWeather()
  renderDayNavigation()
  renderDaysAccordion()
  updateEditButtons()
  loadAttractionPhotos()
  initMap()
  if (window.location.pathname !== '/result') {
    window.history.pushState({}, '', '/result')
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function renderBudget(budget) {
  if (!budget) return '<p class="budget-note">暂无预算信息</p>'
  const items = [
    ['景点门票', budget.total_attractions],
    ['酒店住宿', budget.total_hotels],
    ['餐饮费用', budget.total_meals],
    ['交通费用', budget.total_transportation]
  ]
  return `
    <div class="budget-grid">
      ${items.map(([label, value]) => `
        <div class="budget-item">
          <small>${label}</small>
          <strong>${money(value)}</strong>
        </div>`).join('')}
    </div>
    <div class="budget-total">
      <span>预估总费用</span>
      <strong>${money(budget.total)}</strong>
    </div>`
}

function renderWeather() {
  const weather = currentPlan.weather_info || []
  const section = document.querySelector('#weather')
  section.classList.toggle('hidden', weather.length === 0)
  document.querySelector('#weatherGrid').innerHTML = weather.map((item) => `
    <article class="weather-card">
      <div class="weather-date">${escapeHtml(item.date)}</div>
      <div class="weather-row">
        <i>☀️</i>
        <div><small>白天</small><strong>${escapeHtml(item.day_weather || '待查询')} ${item.day_temp}°C</strong></div>
      </div>
      <div class="weather-row">
        <i>🌙</i>
        <div><small>夜间</small><strong>${escapeHtml(item.night_weather || '待查询')} ${item.night_temp}°C</strong></div>
      </div>
      <div class="weather-wind">💨 ${escapeHtml(item.wind_direction)} ${escapeHtml(item.wind_power)}</div>
    </article>`).join('')
}

function renderDayNavigation() {
  document.querySelector('#sideDayLinks').innerHTML = currentPlan.days.map((day, index) => `
    <button type="button" data-side-day="${index}" class="${index === activeDayIndex ? 'active' : ''}">
      第 ${day.day_index + 1} 天
    </button>`).join('')
}

function renderDaysAccordion() {
  daysAccordion.innerHTML = currentPlan.days.map((day, index) => {
    const active = index === activeDayIndex
    return `
      <article class="collapse-item ${active ? 'active' : ''}">
        <button class="collapse-header" type="button" data-toggle-day="${index}" aria-expanded="${active}">
          <span>第 ${day.day_index + 1} 天</span>
          <small>${formatDate(day.date)}</small>
          <b aria-hidden="true">${active ? '−' : '+'}</b>
        </button>
        <div class="collapse-content ${active ? '' : 'hidden'}">
          ${renderDay(day, index)}
        </div>
      </article>`
  }).join('')
  bindEditableFields()
}

function toggleDay(index) {
  activeDayIndex = index
  renderDayNavigation()
  renderDaysAccordion()
  initMap()
}

function renderDay(day, dayArrayIndex) {
  const attractions = day.attractions.map((place, index) => (
    renderAttraction(place, dayArrayIndex, index, day.attractions.length)
  )).join('')
  const meals = day.meals.map((meal) => `
    <div class="meal-row">
      <b>${mealLabel(meal.type)}</b>
      <span>
        ${escapeHtml(meal.name)}
        ${meal.description ? ` · ${escapeHtml(meal.description)}` : ''}
        ${meal.estimated_cost ? ` · ${money(meal.estimated_cost)}` : ''}
      </span>
    </div>`).join('')
  const hotel = day.hotel ? `
    <div class="section-divider">🏨 推荐酒店</div>
    <article class="hotel-card">
      <h3>${escapeHtml(day.hotel.name)}</h3>
      <div class="hotel-grid">
        <span><b>地址：</b>${escapeHtml(day.hotel.address)}</span>
        <span><b>价格：</b>${escapeHtml(day.hotel.price_range || money(day.hotel.estimated_cost))}</span>
        <span><b>评分：</b>${escapeHtml(day.hotel.rating || '暂无')}</span>
        <span><b>距离：</b>${escapeHtml(day.hotel.distance || '暂无')}</span>
        <span><b>类型：</b>${escapeHtml(day.hotel.type || day.accommodation)}</span>
      </div>
    </article>` : ''

  return `
    <div class="day-panel">
      <div class="day-info">
        <div class="day-info-row"><b>行程描述</b><span>${escapeHtml(day.description)}</span></div>
        <div class="day-info-row"><b>交通方式</b><span>${escapeHtml(day.transportation)}</span></div>
        <div class="day-info-row"><b>住宿安排</b><span>${escapeHtml(day.accommodation)}</span></div>
      </div>
      <div class="section-divider">📍 景点安排</div>
      <div class="attractions-grid">${attractions || '<p>暂无景点安排</p>'}</div>
      ${hotel}
      <div class="section-divider">🍽️ 餐饮安排</div>
      <div class="meal-list">${meals || '<div class="meal-row"><span>暂无餐饮安排</span></div>'}</div>
    </div>`
}

function renderAttraction(place, dayArrayIndex, index, count) {
  const actions = editMode ? `
    <div class="edit-actions">
      <button type="button" data-action="up" data-day="${dayArrayIndex}" data-index="${index}" ${index === 0 ? 'disabled' : ''}>↑</button>
      <button type="button" data-action="down" data-day="${dayArrayIndex}" data-index="${index}" ${index === count - 1 ? 'disabled' : ''}>↓</button>
      <button type="button" class="danger" data-action="delete" data-day="${dayArrayIndex}" data-index="${index}">删</button>
    </div>` : ''
  const body = editMode ? `
    <div class="edit-field">
      <label>景点名称</label>
      <input data-edit-field="name" data-day="${dayArrayIndex}" data-index="${index}" value="${escapeHtml(place.name)}" />
    </div>
    <div class="edit-field">
      <label>地址</label>
      <input data-edit-field="address" data-day="${dayArrayIndex}" data-index="${index}" value="${escapeHtml(place.address)}" />
    </div>
    <div class="edit-field">
      <label>游览时长（分钟）</label>
      <input type="number" min="15" data-edit-field="visit_duration" data-day="${dayArrayIndex}" data-index="${index}" value="${place.visit_duration}" />
    </div>
    <div class="edit-field">
      <label>景点描述</label>
      <textarea data-edit-field="description" data-day="${dayArrayIndex}" data-index="${index}">${escapeHtml(place.description)}</textarea>
    </div>` : `
    <p>📍 ${escapeHtml(place.address)}</p>
    <p>⏱️ 建议游览 ${place.visit_duration} 分钟</p>
    <p>${escapeHtml(place.description)}</p>`

  return `
    <article class="attraction-card">
      <div class="attraction-card-header">
        <h3>${escapeHtml(place.name)}</h3>
        ${actions}
      </div>
      <div class="attraction-image-wrapper">
        <img class="attraction-image" src="${getAttractionImage(place.name, index, place.image_url)}" alt="${escapeHtml(place.name)}" />
        <div class="attraction-badge">${index + 1}</div>
        <div class="price-tag">${place.ticket_price ? money(place.ticket_price) : '免费'}</div>
      </div>
      <div class="attraction-body">${body}</div>
    </article>`
}

function getAttractionImage(name, index, imageUrl = '') {
  if (imageUrl || attractionImages.has(name)) return imageUrl || attractionImages.get(name)
  const gradients = [
    ['#667eea', '#764ba2'],
    ['#f093fb', '#f5576c'],
    ['#4facfe', '#00f2fe'],
    ['#43e97b', '#38f9d7'],
    ['#fa709a', '#fee140']
  ]
  const [start, end] = gradients[index % gradients.length]
  const safeName = String(name).replace(/[<>&]/g, '')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="420"><defs><linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="${start}"/><stop offset="100%" stop-color="${end}"/></linearGradient></defs><rect width="800" height="420" fill="url(#g)"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="Microsoft YaHei,sans-serif" font-size="38" font-weight="bold" fill="white">${safeName}</text></svg>`
  return `data:image/svg+xml;base64,${window.btoa(unescape(encodeURIComponent(svg)))}`
}

async function loadAttractionPhotos() {
  const names = [...new Set(currentPlan.days.flatMap((day) => day.attractions.map((item) => item.name)))]
  await Promise.all(names.map(async (name) => {
    if (attractionImages.has(name)) return
    try {
      const response = await fetch(`/api/poi/photo?name=${encodeURIComponent(name)}`)
      const payload = await response.json()
      if (response.ok && payload.data?.photo_url) {
        attractionImages.set(name, payload.data.photo_url)
      }
    } catch {
      // 图片加载失败时保留本地占位图。
    }
  }))
  document.querySelectorAll('.attraction-image').forEach((image) => {
    const photoUrl = attractionImages.get(image.alt)
    if (photoUrl) image.src = photoUrl
  })
}

function mealLabel(type) {
  return {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐',
    snack: '小吃'
  }[type] || type
}

function bindEditableFields() {
  daysAccordion.querySelectorAll('[data-edit-field]').forEach((input) => {
    input.addEventListener('input', () => {
      const dayIndex = Number(input.dataset.day)
      const attractionIndex = Number(input.dataset.index)
      const field = input.dataset.editField
      currentPlan.days[dayIndex].attractions[attractionIndex][field] = (
        field === 'visit_duration' ? Number(input.value) : input.value
      )
    })
  })
}

daysAccordion.addEventListener('click', (event) => {
  const header = event.target.closest('[data-toggle-day]')
  if (header) {
    toggleDay(Number(header.dataset.toggleDay))
    return
  }
  const action = event.target.closest('[data-action]')
  if (!action) return
  const dayIndex = Number(action.dataset.day)
  const attractionIndex = Number(action.dataset.index)
  if (action.dataset.action === 'delete') {
    deleteAttraction(dayIndex, attractionIndex)
  } else {
    moveAttraction(dayIndex, attractionIndex, action.dataset.action)
  }
})

function toggleEditMode() {
  if (!currentPlan) return
  originalPlan = structuredClone(currentPlan)
  editMode = true
  updateEditButtons()
  renderDaysAccordion()
  showToast('进入编辑模式')
}

function saveChanges() {
  editMode = false
  originalPlan = null
  sessionStorage.setItem('tripPlan', JSON.stringify(currentPlan))
  updateEditButtons()
  renderDaysAccordion()
  initMap()
  showToast('修改已保存')
}

function cancelEdit() {
  if (originalPlan) currentPlan = structuredClone(originalPlan)
  originalPlan = null
  editMode = false
  updateEditButtons()
  renderDaysAccordion()
  initMap()
  showToast('已取消编辑')
}

function moveAttraction(dayIndex, attractionIndex, direction) {
  const items = currentPlan.days[dayIndex].attractions
  const targetIndex = direction === 'up' ? attractionIndex - 1 : attractionIndex + 1
  if (targetIndex < 0 || targetIndex >= items.length) return
  ;[items[attractionIndex], items[targetIndex]] = [items[targetIndex], items[attractionIndex]]
  renderDaysAccordion()
  initMap()
}

function deleteAttraction(dayIndex, attractionIndex) {
  const items = currentPlan.days[dayIndex].attractions
  if (items.length <= 1) {
    showToast('每天至少需要保留一个景点', true)
    return
  }
  items.splice(attractionIndex, 1)
  renderDaysAccordion()
  initMap()
  showToast('景点已删除')
}

function updateEditButtons() {
  document.querySelector('#editButton').classList.toggle('hidden', editMode)
  document.querySelector('#saveButton').classList.toggle('hidden', !editMode)
  document.querySelector('#cancelButton').classList.toggle('hidden', !editMode)
  document.querySelector('#imageButton').classList.toggle('hidden', editMode)
  document.querySelector('#pdfButton').classList.toggle('hidden', editMode)
}

function showToast(message, warning = false) {
  const toast = document.createElement('div')
  toast.textContent = message
  Object.assign(toast.style, {
    position: 'fixed',
    zIndex: '9999',
    top: '80px',
    left: '50%',
    transform: 'translateX(-50%)',
    padding: '10px 18px',
    borderRadius: '6px',
    color: '#fff',
    background: warning ? '#faad14' : '#52c41a',
    boxShadow: '0 6px 20px rgba(0,0,0,.2)'
  })
  document.body.appendChild(toast)
  window.setTimeout(() => toast.remove(), 1800)
}

async function exportAsImage() {
  if (!window.html2canvas) {
    showToast('图片导出组件未加载', true)
    return
  }
  let exportContainer = null
  try {
    exportContainer = createExportContainer()
    const canvas = await window.html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 1,
      logging: false,
      useCORS: true,
      allowTaint: false
    })
    const link = document.createElement('a')
    link.download = `旅行计划_${currentPlan.city}_${Date.now()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
  } catch (error) {
    console.error('图片导出失败:', error)
    showToast('图片导出失败，请稍后重试', true)
  } finally {
    exportContainer?.remove()
  }
}

async function exportAsPDF() {
  if (!window.html2canvas || !window.jspdf?.jsPDF) {
    window.print()
    return
  }
  let exportContainer = null
  try {
    exportContainer = createExportContainer()
    const canvas = await window.html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 1,
      logging: false,
      useCORS: true,
      allowTaint: false
    })
    const image = canvas.toDataURL('image/png')
    const pdf = new window.jspdf.jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
    const width = 210
    const pageHeight = 297
    const height = canvas.height * width / canvas.width
    let remaining = height
    let position = 0
    pdf.addImage(image, 'PNG', 0, position, width, height)
    remaining -= pageHeight
    while (remaining > 0) {
      position = remaining - height
      pdf.addPage()
      pdf.addImage(image, 'PNG', 0, position, width, height)
      remaining -= pageHeight
    }
    pdf.save(`旅行计划_${currentPlan.city}_${Date.now()}.pdf`)
  } catch (error) {
    console.error('PDF导出失败:', error)
    showToast('PDF导出失败，请稍后重试', true)
  } finally {
    exportContainer?.remove()
  }
}

function createExportContainer() {
  const element = document.querySelector('#mainContent')
  const container = element.cloneNode(true)
  const mapClone = container.querySelector('#mapCanvas')
  if (mapClone) {
    mapClone.innerHTML = '<div style="height:430px;display:grid;place-items:center;color:#667eea;background:#eef1ff;font-size:18px">地图请在在线页面查看</div>'
  }
  container.querySelectorAll('img').forEach((image) => {
    const placeholder = document.createElement('div')
    placeholder.textContent = image.alt || '景点图片'
    placeholder.style.cssText = 'width:100%;height:210px;display:grid;place-items:center;color:#fff;background:linear-gradient(135deg,#667eea,#764ba2);font-size:22px;font-weight:700'
    image.replaceWith(placeholder)
  })
  container.style.cssText = `position:fixed;left:-100000px;top:0;width:${element.scrollWidth}px;background:#f5f7fa;padding:20px`
  document.body.appendChild(container)
  return container
}

async function ensureAmap() {
  if (!amapApiPromise) {
    amapApiPromise = (async () => {
      if (!window.AMapLoader) throw new Error('高德地图加载器不可用，请检查网络连接')
      const response = await fetch('/api/maps/config', { cache: 'no-store' })
      if (!response.ok) throw new Error('无法读取高德地图配置')
      const config = await response.json()
      if (!config.enabled) {
        throw new Error('请在 .env 中配置 AMAP_JS_KEY 和 AMAP_JS_SECURITY_CODE，然后重启服务')
      }
      window._AMapSecurityConfig = { securityJsCode: config.security_code }
      return window.AMapLoader.load({
        key: config.key,
        version: '2.0',
        plugins: ['AMap.Marker', 'AMap.Polyline', 'AMap.InfoWindow']
      })
    })()
  }
  return amapApiPromise
}

async function initMap() {
  try {
    const AMap = await ensureAmap()
    if (amapMap) amapMap.destroy()
    amapMap = new AMap.Map('mapCanvas', {
      zoom: 12,
      center: [116.397128, 39.916527],
      viewMode: '3D'
    })
    const activeDay = currentPlan.days[activeDayIndex]
    const attractions = []
    activeDay.attractions.forEach((place, attractionIndex) => {
      if (
        Number.isFinite(Number(place.location?.longitude)) &&
        Number.isFinite(Number(place.location?.latitude))
      ) {
        attractions.push({ ...place, dayIndex: activeDayIndex, attractionIndex })
      }
    })
    if (!attractions.length) {
      showMapState(`第 ${activeDayIndex + 1} 天没有可展示的坐标。`)
      return
    }
    const markers = attractions.map((place, index) => createMarker(place, index, AMap))
    amapMap.add(markers)
    drawRoutes(AMap, attractions)
    amapMap.setFitView(markers)
    hideMapState()
  } catch (error) {
    showMapState(error.message)
  }
}

function createMarker(place, index, AMap) {
  const marker = new AMap.Marker({
    position: [place.location.longitude, place.location.latitude],
    title: place.name,
    label: {
      content: `<div class="map-marker">${index + 1}</div>`,
      offset: new AMap.Pixel(0, -30)
    }
  })
  const infoWindow = new AMap.InfoWindow({
    content: `
      <div class="map-popup">
        <strong>${escapeHtml(place.name)}</strong>
        <span>${escapeHtml(place.address)}</span>
        <span>建议游览 ${place.visit_duration} 分钟</span>
        <em>第 ${place.dayIndex + 1} 天 · 景点 ${place.attractionIndex + 1}</em>
      </div>`,
    offset: new AMap.Pixel(0, -30)
  })
  marker.on('click', () => infoWindow.open(amapMap, marker.getPosition()))
  return marker
}

function drawRoutes(AMap, attractions) {
  if (attractions.length < 2) return
  const polyline = new AMap.Polyline({
    path: attractions.map((place) => [place.location.longitude, place.location.latitude]),
    strokeColor: '#1890ff',
    strokeWeight: 4,
    strokeOpacity: 0.8,
    strokeStyle: 'solid',
    showDir: true
  })
  amapMap.add(polyline)
}

function showMapState(message) {
  mapState.textContent = message
  mapState.classList.remove('hidden')
}

function hideMapState() {
  mapState.classList.add('hidden')
}

function goBack() {
  resultView.classList.add('hidden')
  homeView.classList.remove('hidden')
  window.history.pushState({}, '', '/')
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

document.querySelector('#backButton').addEventListener('click', goBack)
document.querySelector('#editButton').addEventListener('click', toggleEditMode)
document.querySelector('#saveButton').addEventListener('click', saveChanges)
document.querySelector('#cancelButton').addEventListener('click', cancelEdit)
document.querySelector('#imageButton').addEventListener('click', exportAsImage)
document.querySelector('#pdfButton').addEventListener('click', exportAsPDF)
document.querySelector('#backTopButton').addEventListener('click', () => {
  window.scrollTo({ top: 0, behavior: 'smooth' })
})
form.elements.start_date.addEventListener('change', updateTravelDays)
form.elements.end_date.addEventListener('change', updateTravelDays)

document.querySelector('#sideNav').addEventListener('click', (event) => {
  const dayButton = event.target.closest('[data-side-day]')
  if (dayButton) {
    toggleDay(Number(dayButton.dataset.sideDay))
    document.querySelector('#days').scrollIntoView({ behavior: 'smooth', block: 'start' })
    return
  }
  const sectionButton = event.target.closest('[data-section]')
  if (!sectionButton) return
  document.querySelectorAll('#sideNav [data-section]').forEach((button) => {
    button.classList.remove('active')
  })
  sectionButton.classList.add('active')
  document.querySelector(`#${sectionButton.dataset.section}`)?.scrollIntoView({
    behavior: 'smooth',
    block: 'start'
  })
})

window.addEventListener('popstate', () => {
  if (window.location.pathname === '/result' && currentPlan) {
    homeView.classList.add('hidden')
    resultView.classList.remove('hidden')
  } else {
    resultView.classList.add('hidden')
    homeView.classList.remove('hidden')
  }
})

initializeDates()

const savedPlan = sessionStorage.getItem('tripPlan')
if (window.location.pathname === '/result' && savedPlan) {
  try {
    const parsedPlan = JSON.parse(savedPlan)
    if (!hasCompleteMapCoordinates(parsedPlan)) {
      throw new Error('旧行程缺少地图坐标')
    }
    renderResult(parsedPlan)
  } catch {
    sessionStorage.removeItem('tripPlan')
    window.history.replaceState({}, '', '/')
  }
}
