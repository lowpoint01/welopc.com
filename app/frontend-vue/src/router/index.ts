import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import FeedView from '../views/FeedView.vue'
import DailyView from '../views/DailyView.vue'
import MpView from '../views/MpView.vue'
import OpcView from '../views/OpcView.vue'
import AboutView from '../views/AboutView.vue'
import FeedbackView from '../views/FeedbackView.vue'

export const routes = [
  { path: '/', name: 'home', component: HomeView, meta: { label: '首页', subtitle: '今日 AI 信号总览' } },
  { path: '/selected', name: 'selected', component: FeedView, meta: { label: '精选', mode: 'selected', subtitle: '高置信度必看信号' } },
  { path: '/feed', name: 'feed', component: FeedView, meta: { label: '全部 AI 动态', mode: 'all', subtitle: '全量实时信号流' } },
  { path: '/daily', name: 'daily', component: DailyView, meta: { label: 'AI 日报', subtitle: '按天整理的主题阅读器' } },
  { path: '/mp', name: 'mp', component: MpView, meta: { label: '公众号爆文', subtitle: '公众号文章热度与相关度观察' } },
  { path: '/opc', name: 'opc', component: OpcView, meta: { label: 'OPC一人公司', subtitle: '适合一人公司落地的机会信号' } },
  { path: '/about', name: 'about', component: AboutView, meta: { label: '关于', subtitle: '信号筛选规则' } },
  { path: '/feedback', name: 'feedback', component: FeedbackView, meta: { label: '反馈', subtitle: '内容和信源建议' } },
]

export default createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})
