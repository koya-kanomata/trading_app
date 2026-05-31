package com.example.recoweb;

import java.time.Instant;
import java.util.List;

public record RecommendationSnapshot(
        Instant lastUpdated,
        List<RecommendationRow> buyRows,
        List<RecommendationRow> sellRows
) {
}
