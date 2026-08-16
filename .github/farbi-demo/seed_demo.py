import os
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

from application import (
    ORDER_STATUS_DELIVERED,
    Category,
    Design,
    Order,
    Review,
    User,
    app,
    db,
)

PASSWORD = os.environ.get("DEMO_PASSWORD", "Password123")


def ensure_demo_data():
    with app.app_context():
        admin = User.query.filter_by(username="admin_seed").one()
        customer = User.query.filter_by(username="customer_seed").one()
        admin.email_verified = True
        customer.email_verified = True

        designer = User.query.filter_by(username="designer_seed").first()
        if designer is None:
            designer = User(
                username="designer_seed",
                email="designer_seed@example.com",
                is_designer=True,
                email_verified=True,
                bio="Demo designer account populated with sample marketplace products.",
            )
            designer.set_password(PASSWORD)
            db.session.add(designer)
            db.session.flush()
        else:
            designer.is_designer = True
            designer.email_verified = True
            designer.set_password(PASSWORD)

        category_specs = [
            ("Home & Living", None, 10),
            ("Decor", "Home & Living", 11),
            ("Accessories", None, 20),
            ("Toys & Games", None, 30),
        ]
        categories = {}
        for name, parent_name, display_order in category_specs:
            category = Category.query.filter_by(name=name).first()
            if category is None:
                category = Category(name=name, is_active=True, display_order=display_order)
                db.session.add(category)
                db.session.flush()
            category.is_active = True
            categories[name] = category
        categories["Decor"].parent_id = categories["Home & Living"].id

        upload_root = Path(app.config["LOCAL_UPLOAD_ROOT"])
        preview_root = upload_root / "images" / "design_previews"
        model_root = upload_root / "models"
        preview_root.mkdir(parents=True, exist_ok=True)
        model_root.mkdir(parents=True, exist_ok=True)

        products = [
            ("Geometric Planter", "Modern low-poly planter for desks and shelves.", "Decor", "demo_planter", Decimal("29.900"), (68, 116, 160)),
            ("Modular Desk Organizer", "Stackable organizer modules for pens, notes and cables.", "Home & Living", "demo_organizer", Decimal("39.500"), (72, 128, 92)),
            ("Cable Clip Set", "A practical set of reusable desk cable clips.", "Accessories", "demo_cable_clips", Decimal("14.900"), (38, 137, 126)),
            ("Mini Robot Figure", "Friendly articulated robot figure for display or play.", "Toys & Games", "demo_robot", Decimal("34.000"), (124, 92, 154)),
            ("Honeycomb Lamp Shade", "Decorative honeycomb lamp shade with soft geometric texture.", "Decor", "demo_lamp", Decimal("49.900"), (191, 129, 45)),
            ("Custom Name Plate", "Personalizable desk name plate for gifts and workspaces.", "Accessories", "demo_nameplate", Decimal("24.500"), (180, 79, 73)),
        ]

        designs = []
        for index, (title, description, category, stem, price, rgb) in enumerate(products, start=1):
            base_blob = f"images/design_previews/{stem}"
            design = Design.query.filter_by(title=title, designer_id=designer.id).first()
            if design is None:
                design = Design(
                    title=title,
                    description=description,
                    file_path=f"models/{stem}.stl",
                    image_path_1=base_blob,
                    designer_id=designer.id,
                    category=category,
                )
                db.session.add(design)
            design.status = "approved"
            design.is_active_in_marketplace = True
            design.is_archived = False
            design.is_manually_featured = index <= 4
            design.is_featured_on_profile = index <= 2
            design.is_customizable = title == "Custom Name Plate"
            design.royalty_amount = Decimal("5.000")
            design.printing_price = max(Decimal("5.000"), price - Decimal("10.000"))
            design.packaging_price = Decimal("5.000")
            design.final_selling_price = price
            design.available_colors = "Black,White,Blue,Red"
            design.average_rating = Decimal("4.5") if index <= 3 else Decimal("4.0")
            design.review_count = 1 if index <= 3 else 0
            design.view_count = 20 * index
            designs.append(design)

            for suffix, size in (("_thumb", 300), ("_medium", 800), ("_large", 1200)):
                for extension in ("jpg", "webp"):
                    image = Image.new("RGB", (size, size), rgb)
                    draw = ImageDraw.Draw(image)
                    draw.rectangle(
                        (size * 0.08, size * 0.08, size * 0.92, size * 0.92),
                        outline="white",
                        width=max(3, size // 100),
                    )
                    draw.text((size * 0.12, size * 0.45), title[:24], fill="white")
                    image.save(preview_root / f"{stem}{suffix}.{extension}", quality=88)
            (model_root / f"{stem}.stl").write_text(
                "solid demo\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid demo\n",
                encoding="utf-8",
            )

        db.session.flush()

        review_comments = [
            "Excellent sample product and clean finish.",
            "Useful design and easy to understand.",
            "Great demo item for testing the marketplace.",
        ]
        for index, design in enumerate(designs[:3]):
            review = Review.query.filter_by(design_id=design.id, user_id=customer.id).first()
            if review is None:
                db.session.add(
                    Review(
                        design_id=design.id,
                        user_id=customer.id,
                        rating=5 if index != 1 else 4,
                        comment=review_comments[index],
                    )
                )

        if Order.query.filter_by(batch_id="DEMO-BATCH-001").count() == 0:
            for design in designs[:2]:
                db.session.add(
                    Order(
                        status=ORDER_STATUS_DELIVERED,
                        customer_name="Demo Customer",
                        customer_address="123 Demo Street, Tunis",
                        customer_phone="+216 20 000 000",
                        customer_email=customer.email,
                        user_id=customer.id,
                        design_id=design.id,
                        design_title=design.title,
                        total_price=design.final_selling_price,
                        payment_method="cod",
                        payment_status="paid",
                        batch_id="DEMO-BATCH-001",
                        selected_color="Black",
                    )
                )

        db.session.commit()
        design_ids = [design.id for design in designs]
        Path("instance/demo_design_ids.txt").write_text(
            ",".join(str(value) for value in design_ids), encoding="utf-8"
        )
        print(
            {
                "admin": admin.id,
                "customer": customer.id,
                "designer": designer.id,
                "design_ids": design_ids,
                "reviews": 3,
                "orders": 2,
            }
        )


if __name__ == "__main__":
    ensure_demo_data()
