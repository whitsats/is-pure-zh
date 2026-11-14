package org.ispure.demo;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.os.Bundle;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** A small, standalone native Android scene, not a PS2 emulator. */
public final class MainActivity extends Activity {
    private SceneView scene;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().getDecorView().setSystemUiVisibility(
                View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                        | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                        | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        try {
            scene = new SceneView(this);
            setContentView(scene);
        } catch (IOException error) {
            new AlertDialog.Builder(this).setTitle("无法打开体验版")
                    .setMessage("场景资源读取失败，请重新安装体验版。")
                    .setPositiveButton("关闭", (dialog, which) -> finish()).show();
        }
    }

    @Override public void onBackPressed() {
        new AlertDialog.Builder(this).setTitle("开场体验")
                .setItems(new String[]{"从头开始", "返回游戏", "退出"}, (dialog, which) -> {
                    if (which == 0 && scene != null) scene.restart();
                    if (which == 2) finish();
                }).show();
    }

    private static final class SceneView extends View {
        private static final float W = 640f, H = 448f;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG | Paint.FILTER_BITMAP_FLAG);
        private final Rect source;
        private final Bitmap image;
        private final Bitmap portrait, plainFrame, plainBackground, speakerFrame, speakerBackground, nameFrame, nameBackground;
        private final List<String> lines = new ArrayList<>();
        private final SharedPreferences progress;
        private int page;

        SceneView(Context context) throws IOException {
            super(context);
            try (java.io.InputStream input = context.getAssets().open("opening.png")) {
                image = BitmapFactory.decodeStream(input);
            }
            if (image == null) throw new IOException("Invalid opening image");
            portrait = loadImage(context, "iori_portrait.png");
            plainFrame = loadImage(context, "ui_plain_frame.png");
            plainBackground = loadImage(context, "ui_plain_bg.png");
            speakerFrame = loadImage(context, "ui_speaker_frame.png");
            speakerBackground = loadImage(context, "ui_speaker_bg.png");
            nameFrame = loadImage(context, "ui_name_frame.png");
            nameBackground = loadImage(context, "ui_name_bg.png");
            source = new Rect(0, 0, image.getWidth(), image.getHeight());
            try (BufferedReader input = new BufferedReader(new InputStreamReader(
                    context.getAssets().open("opening.txt"), StandardCharsets.UTF_8))) {
                String line;
                while ((line = input.readLine()) != null) {
                    if (!line.trim().isEmpty()) lines.add(line.trim());
                }
            }
            if (lines.isEmpty()) throw new IOException("Missing dialogue");
            progress = context.getSharedPreferences("opening_progress", Context.MODE_PRIVATE);
            page = Math.max(0, Math.min(progress.getInt("page", 0), lines.size()));
            setClickable(true);
            setFocusable(true);
            updateDescription();
        }

        private Bitmap loadImage(Context context, String filename) throws IOException {
            try (java.io.InputStream input = context.getAssets().open(filename)) {
                Bitmap result = BitmapFactory.decodeStream(input);
                if (result == null) throw new IOException("Invalid image: " + filename);
                return result;
            }
        }

        private void drawImage(Canvas canvas, Bitmap bitmap, float x, float y, float width, float height) {
            canvas.drawBitmap(bitmap, null, new RectF(x, y, x + width, y + height), paint);
        }

        private void updateDescription() {
            setContentDescription(page < lines.size() ? lines.get(page) + "。点按继续" : "体验结束，点按从头开始");
        }

        void restart() {
            page = 0;
            progress.edit().putInt("page", page).apply();
            updateDescription();
            invalidate();
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            canvas.drawColor(Color.BLACK);
            float scale = Math.min(getWidth() / W, getHeight() / H);
            float ox = (getWidth() - W * scale) / 2f;
            float oy = (getHeight() - H * scale) / 2f;
            canvas.save();
            canvas.translate(ox, oy);
            canvas.scale(scale, scale);

            // Fill a 4:2.8 viewport while preserving the extracted CG's aspect ratio.
            float factor = Math.max(W / image.getWidth(), H / image.getHeight());
            float iw = image.getWidth() * factor, ih = image.getHeight() * factor;
            paint.setAlpha(255);
            canvas.drawBitmap(image, source, new RectF((W - iw) / 2, (H - ih) / 2,
                    (W + iw) / 2, (H + ih) / 2), paint);

            String text = page < lines.size() ? lines.get(page) : "开场体验到这里结束。";
            boolean spoken = text.startsWith("伊织「") && text.endsWith("」");
            if (spoken) text = text.substring(3, text.length() - 1);
            paint.setColor(Color.WHITE);
            if (spoken) {
                drawImage(canvas, speakerBackground, 8, 248, 624, 200);
                drawImage(canvas, portrait, 13, 296, 145, 145);
                drawImage(canvas, speakerFrame, 8, 248, 624, 200);
                drawImage(canvas, nameBackground, 160, 286, 192, 56);
                drawImage(canvas, nameFrame, 160, 286, 192, 56);
            } else {
                drawImage(canvas, plainBackground, 8, 304, 624, 144);
                drawImage(canvas, plainFrame, 8, 304, 624, 144);
            }
            paint.setColor(Color.WHITE);
            paint.setTextSize(20);
            paint.setFakeBoldText(true);
            paint.setShadowLayer(2, 1, 1, Color.BLACK);
            if (spoken) {
                canvas.drawText("伊织", 256 - paint.measureText("伊织") / 2, 321, paint);
            }
            drawWrapped(canvas, text, spoken ? 174 : 64, spoken ? 367 : 357,
                    spoken ? 407 : 510, 26);
            paint.clearShadowLayer();
            paint.setFakeBoldText(false);
            paint.setTextSize(13);
            paint.setColor(Color.rgb(255, 226, 184));
            String hint = page < lines.size() ? "轻点继续   " + (page + 1) + " / " + lines.size() : "轻点重新开始";
            canvas.drawText(hint, 590 - paint.measureText(hint), 411, paint);

            paint.setTextSize(12);
            paint.setColor(Color.WHITE);
            paint.setShadowLayer(3, 0, 1, Color.BLACK);
            canvas.drawText("I's Pure · 开场体验版", 20, 23, paint);
            paint.clearShadowLayer();
            canvas.restore();
        }

        private void drawWrapped(Canvas canvas, String text, float x, float y, float width, float lineHeight) {
            int start = 0;
            while (start < text.length()) {
                int count = paint.breakText(text, start, text.length(), true, width, null);
                if (count <= 0) break;
                canvas.drawText(text, start, start + count, x, y, paint);
                start += count;
                y += lineHeight;
            }
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            if (event.getAction() == MotionEvent.ACTION_UP) return performClick();
            return true;
        }

        @Override public boolean performClick() {
            super.performClick();
            page = page < lines.size() ? page + 1 : 0;
            progress.edit().putInt("page", page).apply();
            updateDescription();
            invalidate();
            return true;
        }
    }
}
