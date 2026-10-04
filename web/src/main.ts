import './styles/main.css'

import { registerServiceWorker } from './push/register'
import { createLabhqApp } from './shell/app'

createLabhqApp().app.mount('#app')
registerServiceWorker()
