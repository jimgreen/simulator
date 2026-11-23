/**
 * 极地微电网 Web 前端统一多语言引擎（i18n）
 * 默认支持：简体中文（zh-CN）、英文（en-US）、俄文（ru-RU）
 * 扩展新语言：在 SUPPORTED_LANGS 注册语言项，并在 I18N_DICT / PHRASE_TRANSLATIONS 中补充对应译文即可。
 */
const UI_LANG_STORAGE_KEY = "polarUiLang";

const SUPPORTED_LANGS = [
  { code: "zh-CN", label: "中文" },
  { code: "en-US", label: "English" },
  { code: "ru-RU", label: "Русский" },
];

const SUPPORTED_LANG_SET = new Set(SUPPORTED_LANGS.map((item) => item.code));

/**
 * 集中式结构化键值词典（供 data-i18n 与 t(key, params) 直接调用）
 */
const I18N_DICT = {
  "zh-CN": {
    "app.simulator.title": "极地微电网模拟台",
    "app.trainee.title": "极地微电网学员台",
    "app.scada104.title": "模拟台 · IEC104 联动",
    "ui.style": "风格",
    "ui.language": "语言",
    "theme.minimalist-light": "极简明亮",
    "theme.precision-dark": "精密暗黑",
    "theme.bento-grid": "便当盒网格",
    "theme.glassmorphism": "毛玻璃拟态",
    "theme.editorial": "编辑杂志",
    "theme.sci-fi-cyan": "科幻 · 电光青",
    "theme.sci-fi-purple": "科幻 · 赛博紫",
    "theme.sci-fi-matrix": "科幻 · 矩阵绿",
    "toast.themeChanged": "已切换至「{name}」风格",
    "toast.langChanged": "界面语言已切换为：{name}",
    "tree.collapse": "收起",
    "tree.expand": "展开",
    "tree.toggleTitle": "折叠/展开左侧设备树面板",
    "confirm.defaultTitle": "确认执行此操作？",
    "confirm.defaultMessage": "此操作不可撤销，请确认是否继续。",
    "confirm.defaultOk": "确认执行",
    "confirm.cancel": "取消",
    "scada.nav.channels": "通道与指令",
    "scada.nav.points": "四遥点表",
    "scada.nav.logs": "通信日志",
    "scada.nav.backSimulator": "返回模拟台",
    "scada.nav.externalScada": "SCADA 工作台",
    "scada.loading": "正在读取模型",
  },
  "en-US": {
    "app.simulator.title": "Polar Microgrid Simulator",
    "app.trainee.title": "Polar Microgrid Trainee",
    "app.scada104.title": "Simulator · IEC104 Bridge",
    "ui.style": "Theme",
    "ui.language": "Lang",
    "theme.minimalist-light": "Minimalist Light",
    "theme.precision-dark": "Precision Dark",
    "theme.bento-grid": "Bento Grid",
    "theme.glassmorphism": "Glassmorphism",
    "theme.editorial": "Editorial",
    "theme.sci-fi-cyan": "Sci-Fi · Cyan",
    "theme.sci-fi-purple": "Sci-Fi · Cyber Purple",
    "theme.sci-fi-matrix": "Sci-Fi · Matrix Green",
    "toast.themeChanged": "Switched to \"{name}\" theme",
    "toast.langChanged": "Language switched to: {name}",
    "tree.collapse": "Hide",
    "tree.expand": "Show",
    "tree.toggleTitle": "Collapse / expand device tree panel",
    "confirm.defaultTitle": "Confirm this action?",
    "confirm.defaultMessage": "This action cannot be undone. Continue?",
    "confirm.defaultOk": "Confirm",
    "confirm.cancel": "Cancel",
    "scada.nav.channels": "Channels & Commands",
    "scada.nav.points": "Tele-Points",
    "scada.nav.logs": "Comm Logs",
    "scada.nav.backSimulator": "Simulator",
    "scada.nav.externalScada": "SCADA Console",
    "scada.loading": "Loading models...",
  },
  "ru-RU": {
    "app.simulator.title": "Симулятор полярной микросети",
    "app.trainee.title": "Терминал обучаемого микросети",
    "app.scada104.title": "Симулятор · Шлюз IEC104",
    "ui.style": "Стиль",
    "ui.language": "Язык",
    "theme.minimalist-light": "Светлый минимализм",
    "theme.precision-dark": "Точный тёмный",
    "theme.bento-grid": "Бенто-сетка",
    "theme.glassmorphism": "Стекломорфизм",
    "theme.editorial": "Журнальный",
    "theme.sci-fi-cyan": "Sci-Fi · Электроциан",
    "theme.sci-fi-purple": "Sci-Fi · Киберпурпур",
    "theme.sci-fi-matrix": "Sci-Fi · Матрица",
    "toast.themeChanged": "Включён стиль «{name}»",
    "toast.langChanged": "Язык интерфейса: {name}",
    "tree.collapse": "Свернуть",
    "tree.expand": "Показать",
    "tree.toggleTitle": "Свернуть / развернуть дерево оборудования",
    "confirm.defaultTitle": "Подтвердить действие?",
    "confirm.defaultMessage": "Это действие необратимо. Продолжить?",
    "confirm.defaultOk": "Подтвердить",
    "confirm.cancel": "Отмена",
    "scada.nav.channels": "Каналы и команды",
    "scada.nav.points": "Точки ТМ",
    "scada.nav.logs": "Журнал связи",
    "scada.nav.backSimulator": "К симулятору",
    "scada.nav.externalScada": "Пульт SCADA",
    "scada.loading": "Загрузка моделей...",
  },
};

/**
 * 全站三语短语对照表（键：简体中文原文；值：[English, Русский]）
 * 覆盖教员端、学员端与 IEC104 联动页全部静态文案与高频动态状态文案。
 */
const PHRASE_TRANSLATIONS = {
  // 品牌、导航与顶栏
  "极地微电网模拟台": ["Polar Microgrid Simulator", "Симулятор полярной микросети"],
  "极地微电网学员台": ["Polar Microgrid Trainee", "Терминал обучаемого микросети"],
  "模拟台 · IEC104 联动": ["Simulator · IEC104 Bridge", "Симулятор · Шлюз IEC104"],
  "IEC104 联动": ["IEC104 Bridge", "Шлюз IEC104"],
  "返回模拟台": ["Simulator", "К симулятору"],
  "SCADA 工作台": ["SCADA Console", "Пульт SCADA"],
  "主页": ["Overview", "Обзор"],
  "电网模型": ["Grid Model", "Модель сети"],
  "接线图": ["Diagram", "Схема"],
  "曲线设置": ["Curves", "Кривые"],
  "曲线显示": ["Curves", "Кривые"],
  "参数配置": ["Settings", "Параметры"],
  "人工修改": ["Overrides", "Ручные правки"],
  "控制指令": ["Commands", "Команды"],
  "实时量测": ["Measurements", "Измерения"],
  "新能源控制": ["Renewables", "ВИЭ-контроль"],
  "运行日志": ["Logs", "Журнал"],
  "模型管理": ["Models", "Модели"],
  "默认模型": ["Default Model", "Модель по умолч."],
  "当前模型": ["Active Model", "Текущая модель"],
  "交互地址": ["Endpoint", "Адрес обмена"],
  "模型初始化": ["Init Model", "Иниц. модели"],
  "启动接收": ["Start Sync", "Начать приём"],
  "停止接收": ["Stop Sync", "Стоп приёма"],
  "仿真模式": ["Mode", "Режим"],
  "时仿真": ["Hourly", "Час"],
  "日仿真": ["Daily", "День"],
  "周仿真": ["Weekly", "Неделя"],
  "月仿真": ["Monthly", "Месяц"],
  "年仿真": ["Yearly", "Год"],
  "选择时、日、周、月或年仿真": ["Select hourly, daily, weekly, monthly or yearly mode", "Выбор режима: час, день, неделя, месяц, год"],
  "时钟控制": ["Clock", "Часы"],
  "时钟控制操作": ["Clock Controls", "Управление часами"],
  "悬停或点击展开时钟控制": ["Hover or click to open clock controls", "Наведите или нажмите для управления часами"],
  "当前时钟": ["Clock", "Текущее время"],
  "潮流异常": ["PF Alert", "Сбой ПР"],
  "查看未恢复的潮流告警": ["View active power-flow alerts", "Показать активные тревоги ПР"],
  "潮流计算失败，仿真已暂停": ["Power flow failed; simulation paused", "Сбой расчёта режима; симуляция приостановлена"],
  "模拟台潮流计算失败，仿真已暂停": ["Simulator power flow failed; paused", "Сбой расчёта режима на симуляторе; пауза"],
  "暂收起": ["Minimize", "Свернуть"],
  "风格": ["Theme", "Стиль"],
  "语言": ["Lang", "Язык"],
  "选择界面风格": ["Select UI theme", "Выбрать стиль интерфейса"],
  "选择界面语言": ["Select UI language", "Выбрать язык интерфейса"],
  "极简明亮": ["Minimalist Light", "Светлый минимализм"],
  "精密暗黑": ["Precision Dark", "Точный тёмный"],
  "便当盒网格": ["Bento Grid", "Бенто-сетка"],
  "毛玻璃拟态": ["Glassmorphism", "Стекломорфизм"],
  "编辑杂志": ["Editorial", "Журнальный"],
  "科幻 · 电光青": ["Sci-Fi · Cyan", "Sci-Fi · Электроциан"],
  "科幻 · 赛博紫": ["Sci-Fi · Cyber Purple", "Sci-Fi · Киберпурпур"],
  "科幻 · 矩阵绿": ["Sci-Fi · Matrix Green", "Sci-Fi · Матрица"],

  // 通用按钮与状态
  "启动": ["Start", "Пуск"],
  "停止": ["Stop", "Стоп"],
  "暂停": ["Pause", "Пауза"],
  "单步": ["Step", "Шаг"],
  "减速": ["Slower", "Медленнее"],
  "加速": ["Faster", "Быстрее"],
  "保存": ["Save", "Сохранить"],
  "取消": ["Cancel", "Отмена"],
  "确认": ["Confirm", "Подтвердить"],
  "关闭": ["Close", "Закрыть"],
  "刷新": ["Refresh", "Обновить"],
  "删除": ["Delete", "Удалить"],
  "新建": ["New", "Создать"],
  "复制": ["Copy", "Копировать"],
  "导入": ["Import", "Импорт"],
  "导出": ["Export", "Экспорт"],
  "导出 CSV": ["Export CSV", "Экспорт CSV"],
  "搜索": ["Search", "Поиск"],
  "修改": ["Edit", "Изменить"],
  "恢复": ["Restore", "Восстановить"],
  "恢复默认": ["Reset Defaults", "Сбросить"],
  "恢复默认值": ["Reset Defaults", "Сбросить по умолч."],
  "撤销修改": ["Revert", "Отменить правки"],
  "清空所有": ["Clear All", "Очистить всё"],
  "清空日志": ["Clear Logs", "Очистить журнал"],
  "选择所有": ["Select All", "Выбрать все"],
  "知道了": ["Got it", "Понятно"],
  "收起": ["Hide", "Свернуть"],
  "展开": ["Show", "Показать"],
  "是": ["Yes", "Да"],
  "否": ["No", "Нет"],
  "已停止": ["Stopped", "Остановлен"],
  "运行中": ["Running", "Работает"],
  "启动中": ["Starting", "Запуск"],
  "停止中": ["Stopping", "Остановка"],
  "已暂停": ["Paused", "Пауза"],
  "连接中": ["Connecting", "Подключение"],
  "已连接": ["Connected", "Подключено"],
  "已断开": ["Disconnected", "Отключено"],
  "接收中": ["Receiving", "Приём"],
  "接收异常": ["Sync Error", "Ошибка приёма"],
  "本地待命": ["Standby", "Ожидание"],
  "待命": ["Idle", "Ожидание"],
  "待运行": ["Pending", "Ожидание"],
  "待加载": ["Pending", "Загрузка"],
  "待同步": ["Pending", "Синхрон."],
  "告警": ["Alert", "Тревога"],
  "正常": ["Normal", "Норма"],
  "异常": ["Abnormal", "Сбой"],
  "在线": ["Online", "Онлайн"],
  "离线": ["Offline", "Офлайн"],
  "投入": ["In Service", "Вкл."],
  "退出": ["Out of Service", "Выкл."],
  "只读": ["Read-only", "Только чтение"],
  "开环": ["Open-loop", "Разомкнут"],
  "闭环": ["Closed-loop", "Замкнут"],
  "自动": ["Auto", "Авто"],
  "人工": ["Manual", "Ручной"],
  "未知": ["Unknown", "Неизв."],
  "高危确认": ["Confirmation", "Подтверждение"],
  "确认执行": ["Confirm", "Подтвердить"],
  "确认执行操作？": ["Confirm operation?", "Подтвердить операцию?"],
  "确认执行此操作？": ["Confirm this action?", "Подтвердить действие?"],
  "确认下发": ["Send Command", "Отправить"],
  "核对并下发": ["Review & Send", "Проверить и отправить"],
  "操作核对": ["Review", "Проверка"],
  "确认后将立即向模拟台下发遥控指令。": ["The command will be sent to the simulator immediately.", "Команда будет немедленно отправлена на симулятор."],
  "重试保存": ["Retry Save", "Повторить сохранение"],
  "保存并切换": ["Save & Switch", "Сохранить и перейти"],
  "不保存直接切换": ["Discard & Switch", "Перейти без сохранения"],
  "当前曲线存在未保存修改。": ["Current curve has unsaved edits.", "В текущей кривой есть несохранённые изменения."],

  // 主页看板与能量流
  "接收状态": ["Sync State", "Состояние приёма"],
  "数据源": ["Source", "Источник"],
  "模拟台模型": ["Sim Model", "Модель симулятора"],
  "量测": ["Points", "Точки"],
  "可用": ["Valid", "Доступно"],
  "待发": ["Queued", "Очередь"],
  "控制状态": ["Control", "Управление"],
  "时钟状态": ["Clock State", "Состояние часов"],
  "时钟倍率": ["Speed", "Скорость"],
  "模拟时刻": ["Sim Time", "Время симуляции"],
  "当前状态": ["State", "Состояние"],
  "教员数据": ["Instructor Data", "Данные инструктора"],
  "直流电源与负荷侧": ["DC Sources & Loads", "Сторона постоянного тока"],
  "交流电源与负荷侧": ["AC Sources & Loads", "Сторона переменного тока"],
  "交直流汇流母线": ["AC/DC Tie Bus", "Шина связи AC/DC"],
  "绿电功率": ["Green Power", "Мощность ВИЭ"],
  "绿电占比": ["Green Share", "Доля ВИЭ"],
  "风速": ["Wind Speed", "Скорость ветра"],
  "实时风速": ["Live Wind Speed", "Скорость ветра"],
  "太阳辐照": ["Irradiance", "Инсоляция"],
  "实时太阳辐照度": ["Live Solar Irradiance", "Солнечная радиация"],
  "气温": ["Temperature", "Температура"],
  "负荷需求": ["Load Demand", "Нагрузка"],
  "直流母线": ["DC Bus", "Шина DC"],
  "交流母线": ["AC Bus", "Шина AC"],
  "DC/AC变流器": ["DC/AC Inverter", "Инвертор DC/AC"],
  "ACDC变流": ["AC/DC Converter", "Преобразователь AC/DC"],
  "交流": ["AC", "AC"],
  "直流": ["DC", "DC"],
  "光伏": ["PV", "ФЭС"],
  "风电": ["Wind", "ВЭС"],
  "柴发": ["Diesel", "ДГУ"],
  "柴油发电": ["Diesel Gen", "Дизель-ген."],
  "储能": ["Storage", "СНЭ"],
  "构网储能": ["Grid-Forming BESS", "Сетеформирующий СНЭ"],
  "跟网储能": ["Grid-Following BESS", "Сетеведомый СНЭ"],
  "储能SOC": ["BESS SOC", "SOC СНЭ"],
  "构网储能SOC": ["GFM BESS SOC", "SOC СНЭ (GFM)"],
  "跟网储能SOC": ["GFL BESS SOC", "SOC СНЭ (GFL)"],
  "电制氢": ["Electrolyzer", "Электролизер"],
  "电制氢功率": ["Electrolyzer Power", "Мощность электролизера"],
  "燃料电池": ["Fuel Cell", "Топливный элемент"],
  "燃料电池功率": ["Fuel Cell Power", "Мощность ТЭ"],
  "储氢罐": ["H2 Tank", "Бак H2"],
  "储氢罐SOC": ["H2 Tank SOC", "SOC бака H2"],
  "储氢罐压力": ["H2 Pressure", "Давление H2"],
  "储氢罐净流量": ["H2 Net Flow", "Нетто-поток H2"],
  "储氢罐总储气量": ["Total H2 Storage", "Запас H2"],
  "储气压力": ["Gas Pressure", "Давление газа"],
  "产氢流量": ["H2 Output Flow", "Выработка H2"],
  "耗氢流量": ["H2 Input Flow", "Расход H2"],
  "氢能": ["Hydrogen", "Водород"],
  "负荷": ["Load", "Нагрузка"],
  "直流光伏": ["DC PV", "ФЭС DC"],
  "交流光伏": ["AC PV", "ФЭС AC"],
  "直流风电": ["DC Wind", "ВЭС DC"],
  "交流风电": ["AC Wind", "ВЭС AC"],
  "直流并网光伏": ["DC Grid PV", "ФЭС DC"],
  "交流并网光伏": ["AC Grid PV", "ФЭС AC"],
  "直流并网风电": ["DC Grid Wind", "ВЭС DC"],
  "交流并网风电": ["AC Grid Wind", "ВЭС AC"],
  "直流构网储能": ["DC GFM BESS", "СНЭ DC (GFM)"],
  "交流构网储能": ["AC GFM BESS", "СНЭ AC (GFM)"],
  "直流跟网储能": ["DC GFL BESS", "СНЭ DC (GFL)"],
  "交流跟网储能": ["AC GFL BESS", "СНЭ AC (GFL)"],
  "直流平衡储能": ["DC Slack BESS", "Баланс. СНЭ DC"],
  "交流平衡储能": ["AC Slack BESS", "Баланс. СНЭ AC"],
  "直流负荷": ["DC Load", "Нагрузка DC"],
  "交流负荷": ["AC Load", "Нагрузка AC"],
  "发电实时": ["Gen Live", "Генерация"],
  "耗电实时": ["Load Live", "Потребление"],
  "产气实时": ["H2 Prod Live", "Произв. H2"],
  "耗气实时": ["H2 Use Live", "Расход H2"],
  "最新运行事件": ["Latest Runtime Events", "Последние события"],
  "最新交互事件": ["Latest Sync Events", "События обмена"],

  // 设备树、电网模型与接线图
  "设备树": ["Device Tree", "Дерево оборудования"],
  "全部设备": ["All Devices", "Все устройства"],
  "全部类型": ["All Types", "Все типы"],
  "全部来源": ["All Sources", "Все источники"],
  "过滤设备": ["Filter devices...", "Фильтр устройств..."],
  "过滤曲线": ["Filter curves...", "Фильтр кривых..."],
  "过滤量测或设备": ["Filter measurements or devices...", "Фильтр измерений/устройств..."],
  "过滤指令或设备": ["Filter commands or devices...", "Фильтр команд/устройств..."],
  "关键字过滤": ["Keyword filter...", "Фильтр по ключу..."],
  "筛选对象/结果/概要": ["Filter target / result / summary...", "Фильтр объекта / результата..."],
  "设备": ["Device", "Устройство"],
  "设备类型": ["Device Type", "Тип устройства"],
  "名称": ["Name", "Имя"],
  "参数名称": ["Parameter", "Параметр"],
  "当前值": ["Current", "Текущее"],
  "设置值": ["Set Value", "Уставка"],
  "单位": ["Unit", "Ед."],
  "模型参数": ["Model Parameters", "Параметры модели"],
  "显示模型": ["Show Model", "Показать модель"],
  "设备人工操作": ["Manual Device Control", "Ручное управление"],
  "投入设备": ["Bring Online", "Ввести в работу"],
  "退出设备": ["Take Offline", "Вывести из работы"],
  "使设备进入运行状态": ["Put device into service", "Ввести оборудование в работу"],
  "使设备退出运行状态": ["Take device out of service", "Вывести оборудование из работы"],
  "可用操作": ["Available Actions", "Доступные действия"],
  "遥控操作": ["Telecontrol (YK)", "Телеуправление (YK)"],
  "遥调操作": ["Teleregulation (YT)", "Телерегулирование (YT)"],
  "遥控 / 遥调": ["YK / YT Control", "Управление YK / YT"],
  "遥控目标状态": ["Target Switch State", "Целевое состояние"],
  "目标值": ["Target", "Цель"],
  "控制值": ["Control Value", "Уставка"],
  "请选择要执行的人工遥控或遥调操作。": ["Select a manual YK or YT operation to execute.", "Выберите команду ТУ (YK) или ТР (YT)."],

  // 曲线与统计
  "曲线": ["Curves", "Кривые"],
  "曲线列表": ["Curve List", "Список кривых"],
  "环境曲线": ["Weather Curves", "Погодные кривые"],
  "负荷曲线": ["Load Curves", "Кривые нагрузки"],
  "天气与负荷曲线": ["Weather & Load Curves", "Кривые погоды и нагрузки"],
  "配置曲线": ["Configured Curves", "Настроенные кривые"],
  "年曲线数据表": ["Annual Curve Table", "Годовая таблица кривой"],
  "曲线数据表": ["Curve Data Table", "Таблица кривой"],
  "生成典型曲线": ["Generate Typical Curve", "Создать типовую кривую"],
  "曲线形状": ["Shape", "Форма"],
  "正弦": ["Sine", "Синус"],
  "阶梯": ["Step", "Ступень"],
  "锯齿": ["Sawtooth", "Пила"],
  "随机": ["Random", "Случайная"],
  "平均值": ["Mean", "Среднее"],
  "最小值": ["Min", "Мин."],
  "最大值": ["Max", "Макс."],
  "统计指标": ["Statistics", "Статистика"],
  "时间窗口": ["Window", "Окно"],
  "窗口": ["Window", "Окно"],
  "起始日": ["Start Day", "День старта"],
  "起始时刻": ["Start Time", "Время старта"],
  "上一时段": ["Prev", "Пред."],
  "下一时段": ["Next", "След."],
  "回到当前时段": ["Now", "Текущее"],
  "15分钟": ["15 min", "15 мин"],
  "1小时": ["1 hr", "1 ч"],
  "2小时": ["2 hr", "2 ч"],
  "3小时": ["3 hr", "3 ч"],
  "6小时": ["6 hr", "6 ч"],
  "1日": ["1 day", "1 дн"],
  "1周": ["1 wk", "1 нед"],
  "1月": ["1 mo", "1 мес"],
  "1年": ["1 yr", "1 год"],
  "显示选中": ["Selected Only", "Только выбранные"],
  "只显示当前已选择的曲线": ["Show only selected curves", "Показать только выбранные кривые"],
  "选择当前过滤命中的全部曲线": ["Select all filtered curves", "Выбрать все отфильтрованные кривые"],
  "取消选择当前过滤命中的全部曲线": ["Deselect all filtered curves", "Снять выделение со всех кривых"],
  "1小时间隔 · 可编辑": ["1h interval · Editable", "Шаг 1 ч · Редактируемо"],
  "选择参数后生成当前曲线的本地草稿。": ["Choose parameters to generate a local curve draft.", "Задайте параметры для генерации черновика кривой."],

  // 量测、控制指令、故障与人工修改
  "量测值": ["Measured", "Измерено"],
  "真值": ["True Value", "Истина"],
  "实时值": ["Live Value", "Текущее"],
  "量测值与真值": ["Measured vs True", "Измерение и истина"],
  "实时量测值": ["Live Measurements", "Текущие измерения"],
  "测点": ["Point", "Точка"],
  "测点名称": ["Point Name", "Имя точки"],
  "测点跟踪曲线": ["Point Trend", "Тренд точки"],
  "指令跟踪曲线": ["Command Trend", "Тренд команды"],
  "控制跟踪曲线": ["Control Trend", "Тренд управления"],
  "综合功率趋势": ["Aggregate Power Trend", "Сводный тренд мощности"],
  "未选择测点": ["No point selected", "Точка не выбрана"],
  "未选择指令": ["No command selected", "Команда не выбрана"],
  "仅看异常/无效": ["Abnormal Only", "Только сбои"],
  "仅看告警": ["Alerts Only", "Только тревоги"],
  "导出当前筛选的量测数据为 CSV": ["Export filtered measurements to CSV", "Экспортировать измерения в CSV"],
  "只显示有效指令：": ["Active only:", "Только активные:"],
  "当前控制指令": ["Active Commands", "Текущие команды"],
  "当前有效/排队指令": ["Active / Queued Commands", "Активные / в очереди"],
  "当前控制值": ["Current Setpoint", "Текущая уставка"],
  "实时 / 目标": ["Live / Target", "Текущ. / Цель"],
  "有效控制": ["Active Ctrl", "Актив. упр."],
  "有效目标": ["Valid Targets", "Цели"],
  "有效量测": ["Valid Points", "Валидные"],
  "人工指令": ["Manual", "Ручная"],
  "自动指令": ["Auto", "Авто"],
  "遥控": ["YK", "ТУ (YK)"],
  "遥调": ["YT", "ТР (YT)"],
  "遥控指令": ["YK Command", "Команда ТУ"],
  "遥调指令": ["YT Command", "Команда ТР"],
  "设备故障": ["Device Faults", "Отказы оборудования"],
  "量测故障": ["Sensor Faults", "Отказы датчиков"],
  "当前模型没有人工修改": ["No manual overrides in this model", "В этой модели нет ручных правок"],
  "下发": ["Send", "Отправить"],
  "下发仿真时刻": ["Send Sim Time", "Время симуляции"],
  "下发本机时刻": ["Send Local Time", "Локальное время"],

  // 新能源控制
  "单次计算": ["Single Step", "Разовый расчёт"],
  "启动实时控制": ["Start Live Control", "Пуск автоуправления"],
  "停止实时控制": ["Stop Live Control", "Стоп автоуправления"],
  "最近计算": ["Last Run", "Последний расчёт"],
  "新能源": ["Renewables", "ВИЭ"],
  "新能源最大可发": ["Max Renewable", "Макс. ВИЭ"],
  "光伏最大可发": ["Max PV", "Макс. ФЭС"],
  "风电最大可发": ["Max Wind", "Макс. ВЭС"],
  "最大可发": ["Max Avail.", "Макс. дост."],
  "控制策略": ["Strategy", "Стратегия"],
  "控制方式": ["Control Mode", "Режим упр."],
  "控制参数": ["Control Params", "Параметры упр."],
  "控制日志": ["Control Logs", "Журнал упр."],
  "决策过程": ["Decision Trace", "Ход решения"],
  "预校核结果": ["Pre-check", "Предпроверка"],
  "策略预设方案": ["Strategy Preset", "Пресет стратегии"],
  "标准均衡（默认）": ["Balanced (Default)", "Сбалансированный"],
  "新能源积极消纳": ["Max Renewable Uptake", "Макс. использование ВИЭ"],
  "储能/氢能保守保护": ["Conservative BESS / H2", "Щадящий СНЭ / H2"],
  "自定义参数": ["Custom", "Пользовательский"],
  "请选择单次计算或启动实时控制。": ["Run a single calculation or start live control.", "Запустите разовый расчёт или автоуправление."],
  "新能源控制决策详情": ["Renewable Control Decision Details", "Детали решения ВИЭ-контроля"],
  "新能源实时控制运行参数": ["Live Renewable Control Parameters", "Параметры ВИЭ-контроля"],
  "运行与步长": ["Cycle & Steps", "Цикл и шаги"],
  "储能与保护": ["Storage & Limits", "СНЭ и защиты"],
  "氢能与控制": ["Hydrogen Control", "Управление H2"],
  "优化与求解": ["Optimization", "Оптимизация"],
  "电制氢功率参数": ["Electrolyzer Params", "Параметры электролизера"],
  "燃料电池功率参数": ["Fuel Cell Params", "Параметры ТЭ"],
  "储能功率降额": ["BESS Power Derating", "Ограничение мощности СНЭ"],
  "储能充放电降额": ["BESS Charge/Discharge Derating", "Дератинг заряда/разряда СНЭ"],
  "氢能闭环控制": ["H2 Closed-Loop", "Замкнутый контур H2"],
  "高级求解器权重与容差（7 项）": ["Advanced Solver Weights & Tolerances (7)", "Веса и допуски решателя (7)"],

  // 参数配置与模型管理
  "运行参数": ["Runtime Params", "Параметры работы"],
  "仿真运行参数": ["Simulation Params", "Параметры симуляции"],
  "后台运行参数": ["Backend Params", "Параметры сервера"],
  "后台运行状态": ["Backend Status", "Статус сервера"],
  "WEB 运行参数": ["Web UI Params", "Параметры Web UI"],
  "WEB参数": ["Web Params", "Web-параметры"],
  "WEB参数模型": ["Web Param Model", "Модель Web-парам."],
  "后台参数": ["Backend Params", "Серверные парам."],
  "前台刷新": ["UI Refresh", "Обновление UI"],
  "前端刷新": ["UI Refresh", "Обновление UI"],
  "后台刷新": ["Backend Refresh", "Цикл сервера"],
  "前端超时": ["UI Timeout", "Таймаут UI"],
  "后台超时": ["Backend Timeout", "Таймаут сервера"],
  "前端数据刷新周期": ["UI Refresh Interval", "Период обновления UI"],
  "后台数据刷新周期": ["Backend Refresh Interval", "Период цикла сервера"],
  "后台数据刷新周期（仿真周期）": ["Backend Simulation Step Interval", "Период цикла симуляции"],
  "仿真时步": ["Sim Time Step", "Шаг симуляции"],
  "推进步长": ["Step Advance", "Шаг времени"],
  "计算周期": ["Calc Interval", "Период расчёта"],
  "前端请求超时": ["UI Request Timeout", "Таймаут запросов UI"],
  "后台请求超时": ["Backend Request Timeout", "Таймаут запросов сервера"],
  "曲线请求超时": ["Curve Request Timeout", "Таймаут загрузки кривых"],
  "运行日志分页条数": ["Log Page Size", "Строк журнала на стр."],
  "运行日志缓存上限": ["Log Cache Limit", "Лимит кэша журнала"],
  "运行日志详情": ["Log Details", "Детали записи журнала"],
  "遥调响应系数": ["YT Response Factor", "Коэф. отклика ТР"],
  "遥调指令响应系数": ["YT Response Factor", "Коэф. отклика ТР"],
  "新建模型": ["New Model", "Новая модель"],
  "复制模型": ["Clone Model", "Клонировать"],
  "复制新模型": ["Clone Model", "Клонировать модель"],
  "修改模型": ["Edit Model", "Изменить модель"],
  "模型名称": ["Model Name", "Имя модели"],
  "新模型名称": ["New Model Name", "Имя новой модели"],
  "目标模型": ["Target Model", "Целевая модель"],
  "模板模型": ["Template Model", "Шаблон"],
  "导入定义": ["Import Defs", "Импорт пакета"],
  "定义包": ["Def Package", "Пакет модели"],
  "选择 E 文件": ["Choose .e File", "Выбрать .e файл"],
  "选择 SVG 图": ["Choose SVG", "Выбрать SVG"],
  "未选择文件": ["No file chosen", "Файл не выбран"],
  "未选择图形": ["No diagram chosen", "Схема не выбрана"],
  "未选择，保持当前文件": ["Unchanged", "Без изменений"],
  "未选择，保持当前图形": ["Unchanged", "Без изменений"],
  "待导入 E 文件": ["Pending .e file", "Ожидает .e файл"],
  "待导入 SVG 图": ["Pending SVG", "Ожидает SVG"],
  "开始初始化": ["Start Init", "Начать иниц."],
  "初始化": ["Initialize", "Инициализация"],
  "模拟台服务": ["Simulator Service", "Служба симулятора"],
  "模拟台服务地址": ["Simulator URL", "Адрес симулятора"],
  "学员台交互地址": ["Trainee Endpoint", "Адрес терминала"],
  "复制地址": ["Copy URL", "Копировать URL"],
  "自定义地址": ["Custom URL", "Свой адрес"],
  "自定义地址...": ["Custom URL...", "Свой адрес..."],
  "访问链接": ["Access URL", "Ссылка доступа"],
  "地址": ["Address", "Адрес"],
  "端口": ["Port", "Порт"],
  "类型": ["Type", "Тип"],
  "来源": ["Source", "Источник"],
  "状态": ["Status", "Статус"],
  "时间": ["Time", "Время"],
  "级别": ["Level", "Уровень"],
  "内容": ["Message", "Сообщение"],
  "日志": ["Log", "Журнал"],
  "日志类型": ["Log Type", "Тип журнала"],
  "详细信息": ["Details", "Подробности"],
  "多学员台共享": ["Multi-Trainee Shared", "Общий доступ"],
  "127.0.0.1（本机回环）": ["127.0.0.1 (Loopback)", "127.0.0.1 (Локальный)"],
  "0.0.0.0（全部网卡）": ["0.0.0.0 (All Interfaces)", "0.0.0.0 (Все интерфейсы)"],

  // IEC104 联动页
  "通道与指令": ["Channels & Commands", "Каналы и команды"],
  "四遥点表": ["Tele-Points", "Точки ТМ"],
  "通信日志": ["Comm Logs", "Журнал связи"],
  "模型通道状态": ["Model Channel Status", "Состояние каналов моделей"],
  "刷新状态": ["Refresh Status", "Обновить статус"],
  "刷新点表": ["Refresh Points", "Обновить точки"],
  "刷新日志": ["Refresh Logs", "Обновить журнал"],
  "立即刷新模型通道状态": ["Refresh model channel status now", "Обновить статус каналов"],
  "重新读取当前模型控制点列表": ["Reload control points for selected model", "Перезагрузить список точек"],
  "模型": ["Model", "Модель"],
  "IEC104 地址": ["IEC104 Address", "Адрес IEC104"],
  "通道与点表操作": ["Channel & Point Actions", "Действия"],
  "正在读取模型": ["Loading models...", "Загрузка моделей..."],
  "下发仿真指令": ["Send Simulation Command", "Отправка команды симуляции"],
  "筛选控制点名称或点号…": ["Filter control point name or no...", "Фильтр имени или номера точки..."],
  "筛选测点名称或点号…": ["Filter point name or no...", "Фильтр имени или номера точки..."],
  "选择模型": ["Select Model", "Выбрать модель"],
  "请先选择模型": ["Select a model first", "Сначала выберите модель"],
  "控制点": ["Control Point", "Точка управления"],
  "指令值": ["Value", "Значение"],
  "输入设定值": ["Enter setpoint", "Введите уставку"],
  "遥测 YC": ["Telemetry YC", "ТИ (YC)"],
  "遥信 YX": ["Telesignaling YX", "ТС (YX)"],
  "遥控 YK": ["Telecontrol YK", "ТУ (YK)"],
  "遥调 YT": ["Teleregulation YT", "ТР (YT)"],
  "1 · 合 / 投入": ["1 · Close / On", "1 · Вкл."],
  "0 · 分 / 退出": ["0 · Open / Off", "0 · Выкл."],
  "点号": ["Point No.", "№ точки"],
  "质量/状态": ["Quality / State", "Качество / Статус"],
  "操作": ["Actions", "Действия"],
  "请选择模型查看点表": ["Select a model to view points", "Выберите модель для просмотра точек"],
  "请选择模型查看通信日志": ["Select a model to view logs", "Выберите модель для просмотра журнала"],
  "IEC104 通信日志": ["IEC104 Communication Logs", "Журнал связи IEC104"],
  "启动通道": ["Start", "Пуск"],
  "停止通道": ["Stop", "Стоп"],
  "点表": ["Points", "Точки"],
  "禁操": ["Disable", "Блокир."],
  "启用": ["Enable", "Вкл."],
  "已禁操": ["Disabled", "Заблок."],
  "可操作": ["Enabled", "Доступно"],
  "无匹配点表": ["No matching points", "Нет совпадений"],
  "暂无通信日志": ["No communication logs", "Нет записей журнала"],
  "暂无在线模型，请在教员端启动模型服务。": ["No online models. Start a model service in Simulator.", "Нет активных моделей. Запустите службу модели в симуляторе."],
  "已发送": ["Sent", "Отправлено"],
  "失败": ["Failed", "Ошибка"],
  "收起侧栏": ["Collapse Sidebar", "Свернуть меню"],
  "展开侧栏": ["Expand Sidebar", "Развернуть меню"],
  "未在日志对象中匹配到设备": ["No matching device found in log entry", "Устройство не найдено в записи журнала"],
  "拖拽调整宽度，双击恢复默认": ["Drag to resize, double-click to reset", "Тяните для ширины, двойной клик — сброс"],
  "隐藏面板": ["Hide Panel", "Скрыть панель"],
  "显示面板": ["Show Panel", "Показать панель"],
  "搜索设备定位…": ["Locate device...", "Найти устройство..."],
  "适应画布": ["Fit View", "По размеру"],
  "潮流箭头": ["Flow Arrows", "Стрелки потоков"],
  "量测层": ["Measurements", "Измерения"],
  "清空筛选": ["Clear Filters", "Сбросить фильтры"],
  "页面": ["Pages", "Разделы"],
  "快捷键": ["Shortcuts", "Горячие клавиши"],
  "调值": ["Adjust", "Уставка"],

  // 主页、边界、曲线与参数配置补充词条（实现静态 HTML 100% 三语全覆盖）
  "输入边界": ["Input Boundaries", "Входные границы"],
  "仿真类型": ["Sim Type", "Тип симуляции"],
  "仿真源名": ["Source Name", "Имя источника"],
  "切换仿真类型": ["Switch simulation type", "Сменить тип симуляции"],
  "启动仿真": ["Start Simulation", "Запуск симуляции"],
  "运行模式": ["Run Mode", "Режим работы"],
  "操作控制": ["Control", "Управление"],
  "当前": ["Live", "Текущ."],
  "目标": ["Target", "Цель"],
  "当前量测": ["Live Reading", "Текущее изм."],
  "等待量测": ["Waiting", "Ожидание"],
  "气流量": ["Gas Flow", "Поток газа"],
  "风": ["W", "В"],
  "光": ["S", "С"],
  "温": ["T", "Т"],
  "倍": ["x", "x"],
  "条": ["items", "зап."],
  "批": ["batches", "пакет."],
  "次": ["times", "раз"],
  "比例": ["Ratio", "Доля"],
  "扰动": ["Noise", "Шум"],
  "置 0": ["Zero", "Обнулить"],
  "系统": ["System", "Система"],
  "值对象": ["Target", "Объект"],
  "复用方式": ["Reuse Mode", "Режим использования"],
  "最后保存": ["Last Saved", "Сохранено"],
  "未写入": ["Not Saved", "Не записано"],
  "日志 --": ["Log --", "Журнал --"],
  "停止/启动时恢复": ["Restore on stop/start", "Сброс при стопе/пуске"],
  "可选 · 替换 model.e": ["Optional · Replace model.e", "Опционально · Заменить model.e"],
  "可选 · 替换接线图": ["Optional · Replace diagram", "Опционально · Заменить схему"],
  "请选择定义导出目录": ["Select export folder for definition package", "Выберите папку для экспорта пакета"],
  "请检查模拟台链接与本地定义。": ["Check simulator endpoint and local definitions.", "Проверьте адрес симулятора и локальный пакет."],
  "下载模拟台模型、图形、量测与控制定义": ["Download model, diagram, measurement & control definitions", "Загрузить модель, схему, точки измерений и управления"],
  "创建一个待初始化的本地模型槽位": ["Create a local model slot pending initialization", "Создать локальный слот модели"],
  "管理学员台本地模型槽位": ["Manage local trainee model slots", "Управление локальными слотами моделей"],

  // 参数说明、保护与新能源高级求解器参数
  "SOC初始值": ["Initial SOC", "Нач. SOC"],
  "储能SOC初始值": ["Initial BESS SOC", "Нач. SOC СНЭ"],
  "SOC死区(%)": ["SOC Deadband (%)", "Мёртвая зона SOC (%)"],
  "SOC越界步长倍率(%)": ["SOC Out-of-Bounds Step Multiplier (%)", "Множитель шага вне SOC (%)"],
  "SOC 越高，上限不升高": ["Higher SOC never raises upper limit", "Рост SOC не повышает верхний предел"],
  "SOC 越高，上限不降低": ["Higher SOC never lowers upper limit", "Рост SOC не снижает верхний предел"],
  "充电 SOC": ["Charge SOC", "SOC заряда"],
  "放电 SOC": ["Discharge SOC", "SOC разряда"],
  "充电功率上限": ["Max Charge Power", "Макс. мощность заряда"],
  "放电功率上限": ["Max Discharge Power", "Макс. мощность разряда"],
  "功率上限": ["Power Limit", "Предел мощности"],
  "按 SOC 分段线性限制最大充放电功率": ["Piecewise-linear charge/discharge power limit by SOC", "Кусочно-линейное ограничение мощности СНЭ по SOC"],
  "柴发下限": ["Diesel Min", "Мин. ДГУ"],
  "柴发出力权重": ["Diesel Output Weight", "Вес мощности ДГУ"],
  "柴发功率保护带(%)": ["Diesel Power Guardband (%)", "Защитная полоса ДГУ (%)"],
  "构网储能功率保护带(%)": ["GFM BESS Power Guardband (%)", "Защитная полоса GFM СНЭ (%)"],
  "新能源弃电权重": ["Curtailment Weight", "Вес ограничения ВИЭ"],
  "新能源步长(%/次决策)": ["Renewable Step (%/cycle)", "Шаг ВИЭ (%/цикл)"],
  "跟网储能步长(%/次决策)": ["GFL BESS Step (%/cycle)", "Шаг GFL СНЭ (%/цикл)"],
  "平衡容差(kW)": ["Balance Tolerance (kW)", "Допуск баланса (кВт)"],
  "平衡松弛告警(kW)": ["Slack Alert Threshold (kW)", "Порог тревоги небаланса (кВт)"],
  "平衡松弛平方权重": ["Slack Quadratic Weight", "Квадр. вес небаланса"],
  "弃电平方权重": ["Curtailment Quadratic Weight", "Квадр. вес ограничения"],
  "电源/储能调节平方权重": ["Gen/BESS Adjustment Weight", "Квадр. вес регулировки"],
  "边界容差(kW)": ["Boundary Tolerance (kW)", "Допуск границ (кВт)"],
  "求解收敛容差": ["Solver Tolerance", "Допуск сходимости"],
  "最大迭代次数": ["Max Iterations", "Макс. итераций"],
  "自动指令有效期(分钟)": ["Auto Command TTL (min)", "Срок автокоманды (мин)"],
  "自动控制周期（仿真秒）": ["Auto Control Cycle (sim s)", "Цикл автоуправления (с)"],
  "制氢能力上限(%)": ["Electrolyzer Max (%)", "Макс. электролизера (%)"],
  "制氢能力下限(%)": ["Electrolyzer Min (%)", "Мин. электролизера (%)"],
  "制氢调节步长(%)": ["Electrolyzer Step (%)", "Шаг электролизера (%)"],
  "制氢调节死区(%)": ["Electrolyzer Deadband (%)", "Мёртвая зона электролизера (%)"],
  "燃电出力上限(%)": ["Fuel Cell Max (%)", "Макс. ТЭ (%)"],
  "燃电出力下限(%)": ["Fuel Cell Min (%)", "Мин. ТЭ (%)"],
  "燃电出力步长(%)": ["Fuel Cell Step (%)", "Шаг ТЭ (%)"],
  "燃电出力死区(%)": ["Fuel Cell Deadband (%)", "Мёртвая зона ТЭ (%)"],
  "氢储罐压力死区(%)": ["H2 Pressure Deadband (%)", "Мёртвая зона давления H2 (%)"],
  "启机电SOC最小值(%)": ["Start Min BESS SOC (%)", "Мин. SOC СНЭ пуска (%)"],
  "启机电SOC最大值(%)": ["Start Max BESS SOC (%)", "Макс. SOC СНЭ пуска (%)"],
  "停机电SOC最大值(%)": ["Stop Max BESS SOC (%)", "Макс. SOC СНЭ стопа (%)"],
  "启机氢SOC最小值(%)": ["Start Min H2 SOC (%)", "Мин. SOC H2 пуска (%)"],
  "停机氢SOC最小值(%)": ["Stop Min H2 SOC (%)", "Мин. SOC H2 стопа (%)"],
  "停机氢SOC最大值(%)": ["Stop Max H2 SOC (%)", "Макс. SOC H2 стопа (%)"],
  "启机柴发出力最小值(%)": ["Start Min Diesel (%)", "Мин. ДГУ пуска (%)"],
  "启机柴发出力最大值(%)": ["Start Max Diesel (%)", "Макс. ДГУ пуска (%)"],
  "停机柴发最小值(%)": ["Stop Min Diesel (%)", "Мин. ДГУ стопа (%)"],
  "停机柴发最大值(%)": ["Stop Max Diesel (%)", "Макс. ДГУ стопа (%)"],
  "柴发出力严格大于该值时，电制氢逐步降功率直至停机": ["Electrolyzer ramps down to stop when diesel exceeds this value", "Электролизер снижает мощность до стопа выше этого порога ДГУ"],
  "柴发出力严格小于该值时，燃料电池逐步降功率直至停机": ["Fuel cell ramps down to stop when diesel falls below this value", "Топливный элемент снижает мощность до стопа ниже порога ДГУ"],
  "氢储SOC严格大于该值时，电制氢逐步降功率直至停机": ["Electrolyzer ramps down to stop when H2 SOC exceeds this value", "Электролизер останавливается при превышении этого SOC H2"],
  "电储SOC严格大于该值时，满足电制氢启机条件之一": ["Electrolyzer start condition met when BESS SOC exceeds this value", "Условие пуска электролизера при превышении SOC СНЭ"],
  "电储SOC严格小于该值时，电制氢逐步降功率直至停机": ["Electrolyzer ramps down to stop when BESS SOC falls below this value", "Электролизер останавливается при падении SOC СНЭ ниже порога"],
  "日志历史批量": ["Log History Batch", "Пакет истории журнала"],
  "日志增量批量": ["Log Delta Batch", "Пакет инкрем. журнала"],
  "同帧持续上限": ["Stale Frame Limit", "Лимит зависшего кадра"],
  "数据帧超时上限": ["Frame Timeout Limit", "Таймаут кадра данных"],
  "接收状态同步周期": ["Sync State Interval", "Период синхр. статуса"],
  "连续异常保护次数": ["Error Trip Count", "Порог ошибок подряд"],
  "量测增量历史上限": ["Delta History Limit", "Лимит истории дельт"],
  "电功率箭头显示门槛": ["Power Arrow Threshold", "Порог стрелки мощности"],
  "氢流量箭头显示门槛": ["H2 Flow Arrow Threshold", "Порог стрелки потока H2"],
  "WEB API 单次请求最长等待": ["Max wait per Web API request", "Макс. ожидание запроса Web API"],
  "WEB 前端读取学员台后台接收状态的周期": ["UI polling interval for trainee sync status", "Период опроса статуса приёма UI"],
  "与模拟台进行实时数据交换的单次最长等待": ["Max wait per simulator exchange request", "Макс. ожидание обмена с симулятором"],
  "学员台页面调用本地 WEB API 的最长等待": ["Max wait for local trainee Web API calls", "Макс. ожидание локального Web API"],
  "学员台后台为增量同步保留的量测变更批次数": ["Measurement delta batches kept by backend", "Число пакетов изменений в кэше сервера"],
  "学员台接收、后台处理和新能源趋势采样周期": ["Trainee sync, processing & trend sampling period", "Период приёма, обработки и выборки ВИЭ"],
  "同一仿真数据帧持续过久时判定接收冻结": ["Mark sync frozen if same frame persists too long", "Фиксация зависания при повторении одного кадра"],
  "接收数据超过该时长后阻断闭环控制下发": ["Block closed-loop commands when data exceeds timeout", "Блокировка замкнутого контура при таймауте данных"],
  "连续接收异常达到该次数后停止接收并告警": ["Stop sync and alert after consecutive errors", "Остановка приёма и тревога после серии ошибок"],
  "后台计算触发间隔，每周期推进一个时钟步长": ["Backend tick interval advancing one clock step", "Интервал цикла расчёта сервера на шаг часов"],
  "每次触发推进量": ["Sim time advance per tick", "Приращение времени за цикл"],
  "按仿真时钟累计，仿真暂停时停止计时": ["Accumulates by simulation clock; pauses when paused", "Накапливается по часам симуляции; стоп на паузе"],
  "向前翻页时单次加载数量": ["Rows loaded per history page", "Строк на страницу истории"],
  "每次实时拉取的最大日志数": ["Max logs fetched per live poll", "Макс. записей за опрос"],
  "浏览器内保留的日志数量": ["Max logs retained in browser", "Лимит записей в браузере"],
  "浏览器内存中保留的运行日志数量": ["Max runtime logs kept in browser memory", "Лимит журнала в памяти браузера"],
  "曲线摘要与序列加载等待时间": ["Timeout for curve summary & series loading", "Таймаут загрузки кривых"],
  "每周期按：目标值 × 系数 + 当前值 × (1 - 系数)": ["Per tick: target × k + current × (1 - k)", "За цикл: цель × k + текущ. × (1 - k)"],
  "页面轮询完成后等待时长": ["Wait interval after each UI poll", "Пауза после опроса UI"],
  "未启动接收时页面轮询完成后的等待时长": ["Idle poll wait interval when sync is stopped", "Пауза опроса при остановленном приёме"],
  "绝对值不超过门槛时隐藏电气潮流箭头": ["Hide electric flow arrow when |value| ≤ threshold", "Скрыть стрелку тока при |знач.| ≤ порога"],
  "绝对值不超过门槛时隐藏氢气流动箭头": ["Hide H2 flow arrow when |value| ≤ threshold", "Скрыть стрелку H2 при |знач.| ≤ порога"],

  // 表格 caption / summary 与 Canvas 图表文案
  "idx 名称 设备属性": ["idx Name Attributes", "idx Имя Атрибуты"],
  "参数名称 当前值 设置值 单位": ["Parameter Current Target Unit", "Параметр Текущее Уставка Ед."],
  "对象 修改类型 参数或状态项 默认值 当前值 修改时间 保存状态": ["Object Type Field Default Current Updated Saved", "Объект Тип Поле По умолч. Текущее Время Статус"],
  "指令类型 设备 设备类型 模式 指令项 控制指令 指令来源 接收本机时刻 接收仿真时刻 实时值 量测值 操作": ["Type Device Category Mode Field Command Source Local Time Sim Time Live Measured Action", "Тип Устр. Категория Режим Поле Команда Источник Лок. время Сим. время Текущ. Измер. Действие"],
  "本机时刻 仿真时刻 类型 对象 结果 概要；双击日志行查看详细信息": ["Local Time Sim Time Type Target Result Summary (double-click row for details)", "Лок. время Сим. время Тип Объект Результат Сводка (двойной клик для деталей)"],
  "设备名称 运行状态 故障启始时刻 结束时刻": ["Device Status Fault Start End Time", "Устройство Статус Начало отказа Конец"],
  "设备类型 设备名称 当前状态 当前模式 运行模式": ["Category Device State Mode Run Mode", "Категория Устройство Состояние Режим Режим работы"],
  "量测名称 设备 量测类型 真值 量测值 偏差 状态": ["Point Device Type True Measured Delta Status", "Точка Устройство Тип Истина Измер. Откл. Статус"],
  "量测状态 正常 死数 0值 中值 误差": ["Sensor State Normal Stuck Zero Mid Bias", "Статус датчика Норма Завис Ноль Среднее Смещение"],
  "年末": ["Year End", "Конец года"],
  "未选择曲线": ["No curve selected", "Кривая не выбрана"],
  "所有曲线已隐藏": ["All curves hidden", "Все кривые скрыты"],
  "暂无跟踪数据": ["No trace data", "Нет данных тренда"],
  "暂无测点跟踪数据": ["No measurement trace data", "Нет данных тренда точки"],
  "暂无指令跟踪数据": ["No command trace data", "Нет данных тренда команды"],
  "请选择控制指令": ["Select a control command", "Выберите команду управления"],
  "快速跳转或搜索命令、页签与设备…": ["Jump to page, device, theme or action...", "Поиск раздела, устройства, темы или команды..."],
  "快捷命令": ["Quick Palette", "Команды"],
  "定位接线图": ["Locate on Diagram", "На схеме"],
  "复制文本": ["Copy", "Копировать"],
  "已复制到剪贴板": ["Copied to clipboard", "Скопировано в буфер"],
  "去下发": ["Send", "Отправить"],
  "暂停自动刷新": ["Pause Auto-Refresh", "Пауза автообновления"],
  "全部级别": ["All Levels", "Все уровни"],
  "筛选日志内容…": ["Filter log messages...", "Фильтр сообщений журнала..."],
  "页面": ["Pages", "Разделы"],
  "操作": ["Actions", "Действия"],
  "适应画布": ["Fit Canvas", "Вписать схему"],
  "切换侧栏": ["Toggle Sidebar", "Переключить панель"],
  "快捷键速查": ["Keyboard Shortcuts", "Горячие клавиши"],
  "清空筛选": ["Clear Filters", "Сбросить фильтры"],
  "定位设备...": ["Find device...", "Найти устройство..."],
  "定位设备": ["Find device", "Найти устройство"],
  "接线图工具栏": ["Diagram Toolbar", "Панель схемы"],
  "切换 SCADA / 真值显示": ["Toggle SCADA / True Value", "Переключить SCADA / Истина"],
  "显示或隐藏潮流方向箭头": ["Toggle Power Flow Arrows", "Показать/скрыть стрелки потока"],
  "显示或隐藏量测值": ["Toggle Measurement Labels", "Показать/скрыть измерения"],
  "潮流": ["Flow", "Потоки"],
  "量测": ["Meas", "Измер."],
  "适应": ["Fit", "Вписать"],
  "放大": ["Zoom In", "Приблизить"],
  "缩小": ["Zoom Out", "Отдалить"],
  "未找到设备": ["Device not found", "Устройство не найдено"],
  "调值": ["Adjust", "Уставка"],
  "打开全局快捷命令面板": ["Open command palette", "Открыть палитру команд"],
  "快速切换左侧主页面": ["Switch primary sidebar tabs", "Переключение разделов"],
  "打开或关闭快捷键速查": ["Toggle shortcuts cheat sheet", "Показать горячие клавиши"],
  "接线图放大 / 缩小": ["Zoom diagram in / out", "Масштаб схемы +/-"],
  "接线图适应画布": ["Fit diagram to viewport", "Вписать схему в окно"],
  "关闭弹窗或取消当前操作": ["Close dialog or cancel", "Закрыть окно / отмена"],
  "未在日志对象中匹配到设备": ["No matching device found in log", "Устройство в журнале не найдено"],
};

/**
 * 动态数字/模板短语翻译规则（覆盖计数角标、空态统计与带参数提示）
 */
const DYNAMIC_PATTERNS = [
  [/^第(\d+)天$/, (m) => [ `Day ${m[1]}`, `День ${m[1]}` ]],
  [/^另有\s*(\d+)\s*条曲线$/, (m) => [ `+${m[1]} more curves`, `ещё ${m[1]} крив.` ]],
  [/^(\d+)\s*台设备$/, (m) => [ `${m[1]} devices`, `${m[1]} устр.` ]],
  [/^(\d+)\s*可用$/, (m) => [ `${m[1]} valid`, `${m[1]} дост.` ]],
  [/^(\d+)\s*待发$/, (m) => [ `${m[1]} queued`, `${m[1]} в оч.` ]],
  [/^(\d+)\s*条$/, (m) => [ `${m[1]} items`, `${m[1]} зап.` ]],
  [/^(\d+)\s*条控制指令$/, (m) => [ `${m[1]} commands`, `${m[1]} команд` ]],
  [/^(\d+)\s*条有效指令$/, (m) => [ `${m[1]} active`, `${m[1]} актив.` ]],
  [/^(\d+)\s*点$/, (m) => [ `${m[1]} pts`, `${m[1]} точ.` ]],
  [/^(\d+)\s*类$/, (m) => [ `${m[1]} types`, `${m[1]} тип.` ]],
  [/^(\d+)\s*项$/, (m) => [ `${m[1]} items`, `${m[1]} поз.` ]],
  [/^(\d+)\s*次$/, (m) => [ `${m[1]}x`, `${m[1]} раз` ]],
  [/^(\d+)\s*类\s*·\s*(\d+)\s*台$/, (m) => [ `${m[1]} types · ${m[2]} units`, `${m[1]} тип. · ${m[2]} устр.` ]],
  [/^全部设备\s*·\s*(\d+)\s*台$/, (m) => [ `All Devices · ${m[1]}`, `Все устр. · ${m[1]}` ]],
  [/^(\d+)\/(\d+)\s*台$/, (m) => [ `${m[1]}/${m[2]} units`, `${m[1]}/${m[2]} устр.` ]],
  [/^最近\s*(\d+)\s*条$/, (m) => [ `Latest ${m[1]}`, `Посл. ${m[1]}` ]],
  [/^(\d+)\s*项修改\s*·\s*已选\s*(\d+)\s*项$/, (m) => [ `${m[1]} overrides · ${m[2]} selected`, `${m[1]} прав. · выбр. ${m[2]}` ]],
  [/^(\d+)\s*点\s*·\s*左轴无\s*·\s*右轴无$/, (m) => [ `${m[1]} pts · Left: none · Right: none`, `${m[1]} точ. · Лев.: нет · Прав.: нет` ]],
];

const HAS_CJK_RE = /[\u4e00-\u9fff]/;
const ORIGINAL_TEXT_CACHE = new WeakMap();
const ORIGINAL_ATTR_CACHE = new WeakMap();
const TRANSLATABLE_ATTRS = ["placeholder", "title", "aria-label"];

let currentLangCode = "zh-CN";
let isApplyingTranslation = false;
let i18nObserver = null;
let pendingObserverFlush = false;

function normalizeUiLang(raw) {
  if (!raw || typeof raw !== "string") return "zh-CN";
  if (SUPPORTED_LANG_SET.has(raw)) return raw;
  const lower = raw.toLowerCase();
  if (lower.startsWith("en")) return "en-US";
  if (lower.startsWith("ru")) return "ru-RU";
  return "zh-CN";
}

function getUiLang() {
  return normalizeUiLang(document.documentElement.lang || currentLangCode);
}

/**
 * 通过键值获取当前语言文案，支持 {param} 占位符替换
 */
function t(key, params = null) {
  const lang = getUiLang();
  const table = I18N_DICT[lang] || I18N_DICT["zh-CN"];
  let text = table[key] ?? I18N_DICT["zh-CN"][key] ?? key;
  if (params && typeof params === "object") {
    for (const [k, v] of Object.entries(params)) {
      text = text.replaceAll(`{${k}}`, String(v));
    }
  }
  return text;
}

/**
 * 将中文短语翻译为目标语言；未命中则返回原文兜底
 */
function translatePhrase(rawText, lang = getUiLang()) {
  if (lang === "zh-CN" || typeof rawText !== "string" || !rawText) return rawText;
  if (!HAS_CJK_RE.test(rawText)) return rawText;
  const trimmed = rawText.trim();
  if (!trimmed) return rawText;
  const langIdx = lang === "ru-RU" ? 1 : 0;

  let translated = null;
  const direct = PHRASE_TRANSLATIONS[trimmed];
  if (direct) {
    translated = direct[langIdx];
  } else {
    for (const [regex, builder] of DYNAMIC_PATTERNS) {
      const match = trimmed.match(regex);
      if (match) {
        translated = builder(match)[langIdx];
        break;
      }
    }
  }
  if (!translated) return rawText;
  const leading = rawText.slice(0, rawText.indexOf(trimmed));
  const trailing = rawText.slice(rawText.indexOf(trimmed) + trimmed.length);
  return `${leading}${translated}${trailing}`;
}

function translateElementNode(el, lang) {
  if (!el || el.nodeType !== 1) return;
  const tag = el.tagName;
  if (tag === "SCRIPT" || tag === "STYLE" || tag === "NOSCRIPT") return;
  if (el.dataset && el.dataset.i18nSkip === "true") return;

  // 1. 显式 data-i18n 键值绑定
  if (el.dataset && el.dataset.i18n) {
    const val = t(el.dataset.i18n);
    if (el.textContent !== val) el.textContent = val;
  }
  if (el.dataset && el.dataset.i18nTitle) {
    el.setAttribute("title", t(el.dataset.i18nTitle));
  }
  if (el.dataset && el.dataset.i18nPlaceholder) {
    el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
  }

  // 2. 属性翻译（placeholder / title / aria-label）
  let cachedAttrs = ORIGINAL_ATTR_CACHE.get(el);
  for (const attr of TRANSLATABLE_ATTRS) {
    const curVal = el.getAttribute(attr);
    if (curVal == null) continue;
    if (!cachedAttrs) {
      cachedAttrs = {};
      ORIGINAL_ATTR_CACHE.set(el, cachedAttrs);
    }
    if (!(attr in cachedAttrs) && HAS_CJK_RE.test(curVal)) {
      cachedAttrs[attr] = curVal;
    }
    if (attr in cachedAttrs) {
      const nextVal = lang === "zh-CN" ? cachedAttrs[attr] : translatePhrase(cachedAttrs[attr], lang);
      if (curVal !== nextVal) el.setAttribute(attr, nextVal);
    }
  }

  // 3. 非显式 data-i18n 元素内的直接文本节点翻译
  if (!el.dataset || !el.dataset.i18n) {
    const children = el.childNodes || [];
    for (let i = 0; i < children.length; i += 1) {
      const node = children[i];
      if (!node || node.nodeType !== 3) continue;
      const curText = node.nodeValue || "";
      let original = ORIGINAL_TEXT_CACHE.get(node);
      if (original === undefined) {
        if (!HAS_CJK_RE.test(curText)) continue;
        original = curText;
        ORIGINAL_TEXT_CACHE.set(node, original);
      } else if (HAS_CJK_RE.test(curText) && curText !== original) {
        // 业务脚本动态写入了新的中文内容，刷新原文缓存
        original = curText;
        ORIGINAL_TEXT_CACHE.set(node, original);
      }
      const nextText = lang === "zh-CN" ? original : translatePhrase(original, lang);
      if (curText !== nextText) {
        node.nodeValue = nextText;
      }
    }
  }

  // 4. 英文/俄文防截断：为无 title 的导航按钮、表头与普通按钮补充悬浮完整文案
  if (lang !== "zh-CN" && (tag === "BUTTON" || tag === "TH" || tag === "A")) {
    const label = (el.textContent || "").trim();
    if (label && !el.getAttribute("title") && label.length >= 8) {
      el.setAttribute("title", label);
    }
  }
}

const SKIP_SVG_TAGS = new Set([
  "SVG", "PATH", "LINE", "CIRCLE", "ELLIPSE", "RECT", "POLYGON", "POLYLINE",
  "DEFS", "SYMBOL", "USE", "G", "TEXT", "TSPAN", "ANIMATEMOTION", "CANVAS",
]);
let pendingDirtyNodes = new Set();

function isSkippableGraphicNode(node) {
  if (!node) return true;
  if (node.namespaceURI === "http://www.w3.org/2000/svg") return true;
  const tag = String(node.tagName || "").toUpperCase();
  if (SKIP_SVG_TAGS.has(tag)) return true;
  if (node.classList && node.classList.contains("numeric-cell")) return true;
  return false;
}

function translateUiTree(root = document.body, lang = getUiLang()) {
  if (!root || isApplyingTranslation) return;
  isApplyingTranslation = true;
  try {
    if (!isSkippableGraphicNode(root)) {
      translateElementNode(root, lang);
    }
    if (typeof root.querySelectorAll === "function") {
      const nodes = root.querySelectorAll("*");
      for (let i = 0; i < nodes.length; i += 1) {
        const node = nodes[i];
        if (isSkippableGraphicNode(node)) continue;
        translateElementNode(node, lang);
      }
    }
  } finally {
    // 清空翻译自身触发的 DOM 变更队列，彻底消除微任务自触发死循环。
    if (i18nObserver && typeof i18nObserver.takeRecords === "function") {
      i18nObserver.takeRecords();
    }
    isApplyingTranslation = false;
  }
}

function flushDirtyI18nNodes() {
  pendingObserverFlush = false;
  const lang = getUiLang();
  if (lang === "zh-CN") {
    pendingDirtyNodes.clear();
    return;
  }
  const batch = Array.from(pendingDirtyNodes);
  pendingDirtyNodes.clear();
  if (!batch.length || isApplyingTranslation) return;
  isApplyingTranslation = true;
  try {
    for (let i = 0; i < batch.length; i += 1) {
      const target = batch[i];
      if (!target || (target.isConnected === false)) continue;
      if (isSkippableGraphicNode(target)) continue;
      translateElementNode(target, lang);
      if (typeof target.querySelectorAll === "function" && target.childElementCount > 0) {
        const sub = target.querySelectorAll("*");
        for (let j = 0; j < sub.length; j += 1) {
          const child = sub[j];
          if (isSkippableGraphicNode(child)) continue;
          translateElementNode(child, lang);
        }
      }
    }
  } finally {
    if (i18nObserver && typeof i18nObserver.takeRecords === "function") {
      i18nObserver.takeRecords();
    }
    isApplyingTranslation = false;
  }
}

function updateDocumentTitle(lang) {
  const titleEl = document.querySelector && document.querySelector("title");
  if (!titleEl) return;
  let orig = ORIGINAL_TEXT_CACHE.get(titleEl);
  if (orig === undefined) {
    orig = document.title || titleEl.textContent || "";
    ORIGINAL_TEXT_CACHE.set(titleEl, orig);
  }
  document.title = lang === "zh-CN" ? orig : translatePhrase(orig, lang);
}

function ensureI18nObserver() {
  if (typeof MutationObserver !== "function" || !document.body) return;
  const lang = getUiLang();
  // 简体中文模式下无需挂载 DOM 观察器，彻底零开销。
  if (lang === "zh-CN") {
    if (i18nObserver) {
      i18nObserver.disconnect();
      i18nObserver = null;
    }
    pendingDirtyNodes.clear();
    pendingObserverFlush = false;
    return;
  }
  if (i18nObserver) return;
  i18nObserver = new MutationObserver((records) => {
    if (isApplyingTranslation || getUiLang() === "zh-CN") return;
    let added = false;
    for (let i = 0; i < records.length; i += 1) {
      const rec = records[i];
      if (rec.type === "characterData") {
        const parent = rec.target && rec.target.parentElement;
        if (parent && !isSkippableGraphicNode(parent)) {
          pendingDirtyNodes.add(parent);
          added = true;
        }
      } else if (rec.type === "childList" && rec.addedNodes && rec.addedNodes.length) {
        for (let j = 0; j < rec.addedNodes.length; j += 1) {
          const node = rec.addedNodes[j];
          if (!node) continue;
          if (node.nodeType === 1 && !isSkippableGraphicNode(node)) {
            pendingDirtyNodes.add(node);
            added = true;
          } else if (node.nodeType === 3 && node.parentElement && !isSkippableGraphicNode(node.parentElement)) {
            pendingDirtyNodes.add(node.parentElement);
            added = true;
          }
        }
      }
    }
    if (!added || pendingObserverFlush) return;
    pendingObserverFlush = true;
    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(flushDirtyI18nNodes);
    } else {
      setTimeout(flushDirtyI18nNodes, 16);
    }
  });
  try {
    i18nObserver.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  } catch (_e) {
    i18nObserver = null;
  }
}

function applyUiLanguage(langCode, { persist = true, notify = false, redraw = true } = {}) {
  const resolved = normalizeUiLang(langCode);
  currentLangCode = resolved;
  document.documentElement.lang = resolved;
  document.documentElement.dataset.lang = resolved;

  const selector = document.getElementById("langSelector");
  if (selector && selector.value !== resolved) {
    selector.value = resolved;
  }

  if (persist) {
    try {
      localStorage.setItem(UI_LANG_STORAGE_KEY, resolved);
    } catch (_e) {}
  }

  updateDocumentTitle(resolved);
  translateUiTree(document.body, resolved);
  ensureI18nObserver();

  if (redraw) {
    if (typeof redrawActiveSimulatorCharts === "function") {
      redrawActiveSimulatorCharts();
    }
    if (typeof redrawActiveTraineeCharts === "function") {
      redrawActiveTraineeCharts();
    }
    if (typeof window !== "undefined" && window.Scada104Module && typeof window.Scada104Module.onLanguageChange === "function") {
      window.Scada104Module.onLanguageChange();
    }
  }

  if (notify && typeof showUiToast === "function") {
    const meta = SUPPORTED_LANGS.find((item) => item.code === resolved) || SUPPORTED_LANGS[0];
    showUiToast(t("toast.langChanged", { name: meta.label }), "info", 2000);
  }
  return resolved;
}

function initUiI18n() {
  let initial = document.documentElement.lang || "zh-CN";
  try {
    const stored = localStorage.getItem(UI_LANG_STORAGE_KEY);
    if (stored) initial = stored;
  } catch (_e) {}
  applyUiLanguage(initial, { persist: false, notify: false, redraw: false });

  const selector = document.getElementById("langSelector");
  if (selector) {
    selector.addEventListener("change", () => {
      applyUiLanguage(selector.value, { persist: true, notify: true, redraw: true });
    });
  }
  window.addEventListener("storage", (event) => {
    if (event.key === UI_LANG_STORAGE_KEY) {
      applyUiLanguage(event.newValue, { persist: false, notify: false, redraw: true });
    }
  });
}
