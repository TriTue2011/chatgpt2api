import express from 'express';
const router = express.Router();

import routesUI from './ui.js';
import routesAPI from './api.js';
import routesChat from './chat.js';
import routesChatApi from './chat-api.js';

router.use('/', routesUI);
router.use('/api', routesAPI);
router.use('/', routesChat);
router.use('/api', routesChatApi);

export default router;
