import express from 'express';
import { zaloAccounts } from '../api/zalo/zalo.js';

const router = express.Router();

router.get('/pwa-manifest', (req, res) => {
    console.log('[PWA] Manifest requested, host:', req.get('host'), 'protocol:', req.protocol);
    res.set('Cache-Control', 'no-store');
    const manifest = JSON.stringify({
        name: 'Zalo Chat',
        short_name: 'Zalo Chat',
        start_url: '/chat',
        id: '/chat',
        display: 'standalone',
        orientation: 'portrait-primary',
        background_color: '#f8f9fb',
        theme_color: '#0068ff',
        icons: [
            { src: '/chat/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
            { src: '/chat/icons/icon-512.png', sizes: '512x512', type: 'image/png' }
        ],
        screenshots: [
            { src: '/chat/icons/screenshot-wide.png', sizes: '1280x720', type: 'image/png', form_factor: 'wide' },
            { src: '/chat/icons/screenshot-narrow.png', sizes: '720x1280', type: 'image/png', form_factor: 'narrow' }
        ]
    });
    res.writeHead(200, { 'Content-Type': 'application/manifest+json' });
    res.end(manifest);
});

router.get('/chat', (req, res) => {
    if (!req.session || !req.session.authenticated) {
        const prefix = req.ingressPath || '';
        return res.redirect(prefix + '/admin-login?redirect=/chat');
    }
    res.set('Cache-Control', 'no-store, no-cache, must-revalidate');
    res.render('chat', {
        username: req.session.username,
        accountCount: zaloAccounts.length
    });
});

export default router;
