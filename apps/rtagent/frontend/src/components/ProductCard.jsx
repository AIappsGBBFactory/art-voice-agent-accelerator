import React, { useState } from 'react';

/**
 * ProductCard Component
 * 
 * Displays individual product information with image, metadata, and pricing.
 * Handles image loading states and errors gracefully.
 * 
 * Props:
 * - product: Product data object from backend (display_product format)
 */
const ProductCard = ({ product }) => {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);

  const {
    product_id,
    name,
    brand,
    price,
    formatted_price,
    sale_price,
    formatted_sale_price,
    on_sale,
    image_url,
    colors = [],
    in_stock,
    stock_status,
    rating,
    review_count,
    description,
  } = product;

  const handleImageLoad = () => {
    console.log(`[ProductCard] Image loaded successfully: ${image_url}`);
    setImageLoaded(true);
  };

  const handleImageError = (e) => {
    console.error(`[ProductCard] Image failed to load: ${image_url}`, e);
    setImageError(true);
    setImageLoaded(true); // Stop showing loading skeleton
  };
  
  // Debug logging
  React.useEffect(() => {
    const isBase64 = image_url && image_url.startsWith('data:image');
    const isHttpUrl = image_url && (image_url.startsWith('http://') || image_url.startsWith('https://'));
    
    console.log('[ProductCard] Rendering product:', {
      product_id,
      name,
      brand,
      has_image_url: !!image_url,
      image_type: isBase64 ? 'base64' : isHttpUrl ? 'http' : 'none',
      image_size: image_url ? `${image_url.length} chars` : '0 chars'
    });
  }, [product_id, name, brand, image_url]);

  return (
    <div style={styles.card}>
      {/* Product Image */}
      <div style={styles.imageContainer}>
        {!imageLoaded && !imageError && (
          <div style={styles.imageSkeleton}>
            <div style={styles.skeletonPulse}></div>
          </div>
        )}
        
        {imageError || !image_url ? (
          <div style={styles.imagePlaceholder}>
            <svg 
              width="64" 
              height="64" 
              viewBox="0 0 24 24" 
              fill="none" 
              stroke="#94a3b8" 
              strokeWidth="1.5"
            >
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
              <circle cx="8.5" cy="8.5" r="1.5"/>
              <polyline points="21 15 16 10 5 21"/>
            </svg>
            <div style={styles.placeholderText}>No Image</div>
          </div>
        ) : (
          <img
            src={image_url}
            alt={`${brand} ${name}`}
            style={{
              ...styles.image,
              opacity: imageLoaded ? 1 : 0,
            }}
            onLoad={handleImageLoad}
            onError={handleImageError}
          />
        )}

        {/* Sale Badge */}
        {on_sale && (
          <div style={styles.saleBadge}>SALE</div>
        )}

        {/* Stock Status */}
        {!in_stock && (
          <div style={styles.outOfStockOverlay}>
            <span style={styles.outOfStockText}>Out of Stock</span>
          </div>
        )}
      </div>

      {/* Product Info */}
      <div style={styles.info}>
        {/* Brand */}
        <div style={styles.brand}>{brand}</div>

        {/* Product Name */}
        <div style={styles.name}>{name}</div>

        {/* Price */}
        <div style={styles.priceContainer}>
          {on_sale && sale_price ? (
            <>
              <span style={styles.salePrice}>{formatted_sale_price}</span>
              <span style={styles.originalPrice}>{formatted_price}</span>
            </>
          ) : (
            <span style={styles.regularPrice}>{formatted_price}</span>
          )}
        </div>

        {/* Colors */}
        {colors.length > 0 && (
          <div style={styles.colorsContainer}>
            {colors.slice(0, 5).map((color, idx) => (
              <div
                key={idx}
                style={{
                  ...styles.colorDot,
                  backgroundColor: getColorHex(color),
                  border: color.toLowerCase() === 'white' ? '1px solid #e2e8f0' : 'none',
                }}
                title={color}
              />
            ))}
            {colors.length > 5 && (
              <span style={styles.moreColors}>+{colors.length - 5}</span>
            )}
          </div>
        )}

        {/* Rating */}
        {rating && review_count > 0 && (
          <div style={styles.ratingContainer}>
            <div style={styles.stars}>
              {[1, 2, 3, 4, 5].map((star) => (
                <span
                  key={star}
                  style={{
                    color: star <= Math.round(rating) ? '#fbbf24' : '#e5e7eb',
                    fontSize: '14px',
                  }}
                >
                  ★
                </span>
              ))}
            </div>
            <span style={styles.reviewCount}>({review_count})</span>
          </div>
        )}

        {/* Stock Status Badge */}
        {in_stock && stock_status !== 'In Stock' && (
          <div style={styles.stockBadge}>{stock_status}</div>
        )}
      </div>
    </div>
  );
};

// Helper function to convert color names to hex values
const getColorHex = (colorName) => {
  const colorMap = {
    // Basic colors
    black: '#000000',
    white: '#FFFFFF',
    red: '#EF4444',
    blue: '#3B82F6',
    navy: '#1E3A8A',
    green: '#10B981',
    yellow: '#FCD34D',
    orange: '#F97316',
    purple: '#A855F7',
    pink: '#EC4899',
    brown: '#92400E',
    gray: '#6B7280',
    grey: '#6B7280',
    beige: '#D4C5B9',
    tan: '#D2B48C',
    cream: '#FFFDD0',
    
    // Extended colors
    maroon: '#800000',
    burgundy: '#800020',
    olive: '#808000',
    teal: '#008080',
    turquoise: '#40E0D0',
    lavender: '#E6E6FA',
    indigo: '#4B0082',
    charcoal: '#36454F',
    khaki: '#C3B091',
    mint: '#98FF98',
  };

  return colorMap[colorName.toLowerCase()] || '#94a3b8'; // Default gray
};

// Styles
const styles = {
  card: {
    flex: '0 0 auto',
    width: '280px',
    backgroundColor: '#ffffff',
    borderRadius: '12px',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.08)',
    overflow: 'hidden',
    transition: 'all 0.3s ease',
    cursor: 'pointer',
    ':hover': {
      boxShadow: '0 4px 16px rgba(0, 0, 0, 0.12)',
      transform: 'translateY(-2px)',
    },
  },
  imageContainer: {
    position: 'relative',
    width: '100%',
    height: '320px',
    backgroundColor: '#f8fafc',
    overflow: 'hidden',
  },
  image: {
    width: '100%',
    height: '100%',
    objectFit: 'cover',
    transition: 'opacity 0.3s ease',
  },
  imageSkeleton: {
    width: '100%',
    height: '100%',
    backgroundColor: '#e2e8f0',
    position: 'relative',
    overflow: 'hidden',
  },
  skeletonPulse: {
    width: '100%',
    height: '100%',
    background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent)',
    animation: 'pulse 1.5s infinite',
  },
  imagePlaceholder: {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f1f5f9',
    color: '#94a3b8',
  },
  placeholderText: {
    marginTop: '12px',
    fontSize: '14px',
    color: '#94a3b8',
  },
  saleBadge: {
    position: 'absolute',
    top: '12px',
    left: '12px',
    backgroundColor: '#EF4444',
    color: '#ffffff',
    fontSize: '12px',
    fontWeight: '600',
    padding: '4px 12px',
    borderRadius: '6px',
    letterSpacing: '0.5px',
  },
  outOfStockOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  outOfStockText: {
    color: '#ffffff',
    fontSize: '16px',
    fontWeight: '600',
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    padding: '8px 16px',
    borderRadius: '8px',
  },
  info: {
    padding: '16px',
  },
  brand: {
    fontSize: '12px',
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    marginBottom: '4px',
  },
  name: {
    fontSize: '16px',
    fontWeight: '500',
    color: '#1e293b',
    marginBottom: '8px',
    lineHeight: '1.4',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  priceContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '12px',
  },
  regularPrice: {
    fontSize: '18px',
    fontWeight: '600',
    color: '#1e293b',
  },
  salePrice: {
    fontSize: '18px',
    fontWeight: '600',
    color: '#EF4444',
  },
  originalPrice: {
    fontSize: '14px',
    color: '#94a3b8',
    textDecoration: 'line-through',
  },
  colorsContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '12px',
  },
  colorDot: {
    width: '20px',
    height: '20px',
    borderRadius: '50%',
    border: 'none',
  },
  moreColors: {
    fontSize: '12px',
    color: '#64748b',
    marginLeft: '2px',
  },
  ratingContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginBottom: '8px',
  },
  stars: {
    display: 'flex',
    gap: '2px',
  },
  reviewCount: {
    fontSize: '12px',
    color: '#64748b',
  },
  stockBadge: {
    display: 'inline-block',
    fontSize: '11px',
    fontWeight: '600',
    color: '#f97316',
    backgroundColor: '#fff7ed',
    padding: '4px 8px',
    borderRadius: '4px',
    marginTop: '4px',
  },
};

// Add CSS animation
if (typeof document !== 'undefined') {
  const style = document.createElement('style');
  style.textContent = `
    @keyframes pulse {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(100%); }
    }
  `;
  if (!document.querySelector('style[data-product-card-animations]')) {
    style.setAttribute('data-product-card-animations', '');
    document.head.appendChild(style);
  }
}

export default ProductCard;
