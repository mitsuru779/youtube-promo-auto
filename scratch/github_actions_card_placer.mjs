/**
 * GitHub Actions用情報カード配置スクリプト (Playwright版)
 * Headless Chrome上でクッキーを読み込み、完全自動でYouTube Studioの情報カードを配置
 */
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const CARD_PLAN_FILE = './scratch/card_plan.json';
const PROGRESS_FILE = './scratch/card_progress_auto.json';
const COOKIES_FILE = './scratch/youtube_cookies.json';

function loadProgress() {
  if (fs.existsSync(PROGRESS_FILE)) return JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf8'));
  return { done: {}, failed: {} };
}

function saveProgress(data) {
  fs.writeFileSync(PROGRESS_FILE, JSON.stringify(data, null, 2));
}

async function main() {
  console.log('=== GitHub Actions情報カード自動配置スクリプト (Playwright) ===');

  if (!fs.existsSync(COOKIES_FILE)) {
    console.error('❌ Cookie file not found!');
    process.exit(1);
  }

  const rawCookies = JSON.parse(fs.readFileSync(COOKIES_FILE, 'utf8'));
  const formattedCookies = rawCookies.map(c => ({
    name: c.name,
    value: c.value,
    domain: c.domain,
    path: c.path,
    expires: c.expires || -1,
    httpOnly: c.httpOnly,
    secure: c.secure,
    sameSite: c.sameSite === 'None' ? 'None' : (c.sameSite === 'Lax' ? 'Lax' : 'Strict')
  }));

  const plan = JSON.parse(fs.readFileSync(CARD_PLAN_FILE, 'utf8'));
  const videoIds = Object.keys(plan);
  const progress = loadProgress();

  const pendingIds = videoIds.filter(id => !progress.done[id] || (progress.done[id].cardsAdded || 0) < 3);
  console.log(`📊 Total Videos: ${videoIds.length} | Pending Target Videos: ${pendingIds.length}`);

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
  });

  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 800 }
  });

  await context.addCookies(formattedCookies);

  const page = await context.newPage();

  let processedCount = 0;
  let totalCardsAdded = 0;

  for (const videoId of pendingIds) {
    const videoEntry = plan[videoId];
    const cards = videoEntry.cards || [];
    console.log(`\n📹 Processing [${videoId}] "${videoEntry.title?.substring(0, 40)}" (${cards.length} cards planned)`);

    try {
      // 1. Navigate to video edit page
      await page.goto(`https://studio.youtube.com/video/${videoId}/edit`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(5000);

      // 2. Click Cards edit pencil in right sidepanel
      const cardsLink = page.locator('#info-cards-editor-link, [id*="cards"]').first();
      if (await cardsLink.isVisible({ timeout: 5000 })) {
        await cardsLink.click();
      } else {
        await page.evaluate(() => { window.scrollTo(0, 800); });
        await page.waitForTimeout(2000);
        await page.click('#info-cards-editor-link');
      }

      await page.waitForTimeout(4000);

      let cardsAdded = 0;

      for (let i = 0; i < cards.length; i++) {
        const card = cards[i];
        
        // Click "+ 動画" button inside modal
        const videoBtn = page.locator('ytcp-icon-button, button').filter({ hasText: '動画' }).first();
        if (await videoBtn.isVisible({ timeout: 5000 })) {
          await videoBtn.click();
          await page.waitForTimeout(3000);

          // Type search title inside picker
          const targetTitle = (card.targetTitle || '').replace(/【.*?】/g, '').substring(0, 6);
          const searchInput = page.locator('#search-yours, input[placeholder*="検索"]').first();
          if (await searchInput.isVisible({ timeout: 3000 })) {
            await searchInput.fill(targetTitle);
            await page.waitForTimeout(2500);
          }

          // Select first hit card
          const firstCard = page.locator('ytcp-entity-card').first();
          if (await firstCard.isVisible({ timeout: 4000 })) {
            await firstCard.click();
            await page.waitForTimeout(2000);

            // Set timestamp
            const tsInput = page.locator('ytcp-media-timestamp-input input').first();
            if (await tsInput.isVisible({ timeout: 3000 })) {
              await tsInput.fill(card.timestamp || '10:00');
              await tsInput.blur();
              await page.waitForTimeout(1000);
            }

            // Click Save inside modal
            const modalSaveBtn = page.locator('ytcp-button, button').filter({ hasText: /保存|完了/ }).first();
            if (await modalSaveBtn.isVisible({ timeout: 3000 })) {
              await modalSaveBtn.click();
              await page.waitForTimeout(2500);
              cardsAdded++;
              console.log(`  ✅ Card ${i+1}/${cards.length} added!`);
            }
          }
        }
      }

      // Final save in main editor
      if (cardsAdded > 0) {
        const mainSaveBtn = page.locator('button, ytcp-button').filter({ hasText: '保存' }).first();
        if (await mainSaveBtn.isVisible({ timeout: 3000 })) {
          await mainSaveBtn.click();
          await page.waitForTimeout(5000);
        }
      }

      progress.done[videoId] = { cardsAdded, ts: new Date().toISOString() };
      console.log(`  ✅ Finished ${videoId}: ${cardsAdded} cards added`);
      totalCardsAdded += cardsAdded;
      processedCount++;

      if (processedCount % 2 === 0) {
        saveProgress(progress);
        console.log(`\n💾 Progress saved. Processed: ${processedCount}, Total Cards Added: ${totalCardsAdded}\n`);
      }

    } catch (err) {
      console.error(`  ❌ Error processing ${videoId}:`, err.message);
    }

    await page.waitForTimeout(2000);
  }

  saveProgress(progress);
  console.log('\n🎉 ALL PENDING VIDEOS FULLY PROCESSED ON GITHUB ACTIONS!');

  await browser.close();
}

main().catch(console.error);
