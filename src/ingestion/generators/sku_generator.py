"""
SKU catalog generator.

Produces a realistic catalog of 50 products across 8 categories.
Each SKU has:
  - Baseline daily demand (drawn from category distributions)
  - Current stock (randomly above/below reorder point to create varied risk profiles)
  - Supplier lead time (category-specific)
  - Viral sensitivity (some products blow up on social, others don't)
"""

from __future__ import annotations

import random
from datetime import datetime, timezone

from src.ingestion.schemas import SKUCategory, SKURecord


# ---------------------------------------------------------------------------
# Category-level parameter distributions
# ---------------------------------------------------------------------------

_CATEGORY_CONFIG: dict[SKUCategory, dict] = {
    SKUCategory.BEAUTY: {
        "lead_time_range": (7, 21),
        "demand_range": (20, 150),   # units/day
        "price_range": (12.0, 95.0),
        "viral_sensitivity_range": (1.5, 4.5),  # beauty goes massively viral
        "products": [
            "Hydrating Serum", "Glow Toner", "SPF50 Sunscreen", "Vitamin C Cream",
            "Retinol Night Cream", "Lip Plumper Gloss", "Brow Lamination Kit",
        ],
    },
    SKUCategory.APPAREL: {
        "lead_time_range": (14, 45),
        "demand_range": (10, 80),
        "price_range": (18.0, 120.0),
        "viral_sensitivity_range": (0.8, 3.5),
        "products": [
            "Viral Dance Shorts", "Cloud Joggers", "Oversized Hoodie",
            "Y2K Cargo Pants", "Linen Blazer", "Mini Slip Dress",
        ],
    },
    SKUCategory.FITNESS: {
        "lead_time_range": (10, 30),
        "demand_range": (5, 60),
        "price_range": (25.0, 180.0),
        "viral_sensitivity_range": (1.0, 3.5),
        "products": [
            "Resistance Band Set", "Adjustable Dumbbell", "Yoga Block Set",
            "Jump Rope Pro", "Ab Roller Wheel", "Foam Roller",
        ],
    },
    SKUCategory.HOME: {
        "lead_time_range": (14, 60),
        "demand_range": (3, 40),
        "price_range": (15.0, 250.0),
        "viral_sensitivity_range": (0.5, 2.5),
        "products": [
            "Aesthetic Desk Lamp", "Linen Throw Blanket", "Scented Candle Set",
            "Bamboo Cutting Board", "Minimalist Clock", "Terrarium Kit",
        ],
    },
    SKUCategory.ELECTRONICS: {
        "lead_time_range": (7, 21),
        "demand_range": (2, 30),
        "price_range": (25.0, 400.0),
        "viral_sensitivity_range": (0.5, 2.0),
        "products": [
            "Mini Projector", "Wireless Charging Pad", "LED Strip Lights",
            "Bluetooth Earbuds", "USB-C Hub", "Ring Light Stand",
        ],
    },
    SKUCategory.FOOD: {
        "lead_time_range": (3, 14),
        "demand_range": (30, 200),
        "price_range": (8.0, 60.0),
        "viral_sensitivity_range": (1.5, 4.0),  # food trends blow up fast
        "products": [
            "Whipped Coffee Mix", "Boba Kit", "Korean BBQ Sauce",
            "Matcha Powder", "Chili Crisp Oil", "Vegan Protein Bar Box",
        ],
    },
    SKUCategory.TOYS: {
        "lead_time_range": (14, 45),
        "demand_range": (5, 60),
        "price_range": (12.0, 80.0),
        "viral_sensitivity_range": (1.2, 4.5),
        "products": [
            "Magnetic Tiles Set", "Kinetic Sand Kit", "Mini Claw Machine",
            "Glow-in-Dark Slime", "Pop-It Fidget Set",
        ],
    },
    SKUCategory.ACCESSORIES: {
        "lead_time_range": (7, 30),
        "demand_range": (8, 100),
        "price_range": (10.0, 95.0),
        "viral_sensitivity_range": (1.0, 3.8),
        "products": [
            "Aesthetic Phone Case", "Pearl Hair Clips", "Mini Crossbody Bag",
            "Layered Necklace Set", "Sunglasses Vintage", "Silk Scrunchie Pack",
        ],
    },
}


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


def generate_sku_catalog(
    num_skus: int = 50,
    seed: int = 42,
) -> list[SKURecord]:
    """
    Generate a synthetic SKU catalog.

    The catalog is seeded for reproducibility. Products are drawn from each
    category proportionally, then extended with numbered variants until
    `num_skus` is reached.

    Args:
        num_skus: Total number of SKUs to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of SKURecord objects, ready to be written to DuckDB.
    """
    rng = random.Random(seed)
    skus: list[SKURecord] = []
    sku_idx = 1

    categories = list(_CATEGORY_CONFIG.keys())

    # Round-robin across categories to ensure balanced representation
    while len(skus) < num_skus:
        for category in categories:
            if len(skus) >= num_skus:
                break

            cfg = _CATEGORY_CONFIG[category]
            products = cfg["products"]
            # Cycle through product names, adding suffix if needed
            product_name_base = products[(sku_idx - 1) % len(products)]
            suffix = f" v{(sku_idx - 1) // len(products) + 1}" if sku_idx > len(products) else ""
            product_name = f"{product_name_base}{suffix}"

            # Draw parameters from ranges
            lead_time = rng.randint(*cfg["lead_time_range"])
            baseline_demand = round(rng.uniform(*cfg["demand_range"]), 1)
            unit_price = round(rng.uniform(*cfg["price_range"]), 2)
            viral_sensitivity = round(rng.uniform(*cfg["viral_sensitivity_range"]), 2)

            # Stock levels: mix of healthy, borderline, and at-risk positions
            # Roughly: 60% healthy (>14 days cover), 25% warning zone, 15% critical zone
            stock_scenario = rng.random()
            if stock_scenario < 0.60:
                # Healthy: 14–60 days of cover
                days_cover = rng.uniform(14, 60)
            elif stock_scenario < 0.85:
                # Warning: 7–14 days of cover
                days_cover = rng.uniform(7, 14)
            else:
                # Critical: 1–7 days of cover
                days_cover = rng.uniform(1, 7)

            current_stock = int(baseline_demand * days_cover)
            reorder_point = int(baseline_demand * lead_time * 1.2)  # 20% safety buffer

            sku = SKURecord(
                sku_id=f"SKU-{sku_idx:04d}",
                name=product_name,
                category=category,
                unit_price_usd=unit_price,
                baseline_daily_demand=baseline_demand,
                current_stock=current_stock,
                supplier_lead_time_days=lead_time,
                reorder_point=reorder_point,
                viral_sensitivity=viral_sensitivity,
                created_at=datetime.now(tz=timezone.utc),
            )
            skus.append(sku)
            sku_idx += 1

    return skus[:num_skus]
