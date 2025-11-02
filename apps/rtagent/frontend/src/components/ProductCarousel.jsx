import React, { useRef, useState } from 'react';
import ProductCard from './ProductCard';

/**
 * ProductCarousel Component
 * 
 * Horizontal scrolling carousel for displaying product search results.
 * Features:
 * - Smooth horizontal scrolling
 * - Navigation arrows (hide when at start/end)
 * - Responsive grid (1 card mobile, 3 cards desktop)
 * - Swipe gesture support
 * 
 * Props:
 * - products: Array of product objects from backend
 * - voiceResponse: Optional voice text to display above carousel
 */
const ProductCarousel = ({ products = [], voiceResponse = '' }) => {
  const scrollContainerRef = useRef(null);
  const [showLeftArrow, setShowLeftArrow] = useState(false);
  const [showRightArrow, setShowRightArrow] = useState(true);

  // Handle scroll to update arrow visibility
  const handleScroll = () => {
    const container = scrollContainerRef.current;
    if (!container) return;

    const { scrollLeft, scrollWidth, clientWidth } = container;
    
    // Show left arrow if scrolled from start
    setShowLeftArrow(scrollLeft > 10);
    
    // Show right arrow if not at end
    setShowRightArrow(scrollLeft < scrollWidth - clientWidth - 10);
  };

  // Scroll left
  const scrollLeft = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    
    const cardWidth = 280; // card width
    const gap = 16; // gap between cards
    const scrollAmount = cardWidth + gap;
    
    container.scrollBy({
      left: -scrollAmount,
      behavior: 'smooth',
    });
  };

  // Scroll right
  const scrollRight = () => {
    const container = scrollContainerRef.current;
    if (!container) return;
    
    const cardWidth = 280;
    const gap = 16;
    const scrollAmount = cardWidth + gap;
    
    container.scrollBy({
      left: scrollAmount,
      behavior: 'smooth',
    });
  };

  // Don't render if no products
  if (!products || products.length === 0) {
    return null;
  }

  return (
    <div style={styles.container}>
      {/* Voice Response Text (if provided) */}
      {voiceResponse && (
        <div style={styles.voiceResponse}>
          {voiceResponse}
        </div>
      )}

      {/* Product Count Header */}
      <div style={styles.header}>
        <span style={styles.productCount}>
          {products.length} {products.length === 1 ? 'Product' : 'Products'} Found
        </span>
      </div>

      {/* Carousel Container */}
      <div style={styles.carouselWrapper}>
        {/* Left Arrow */}
        {showLeftArrow && (
          <button
            style={{ ...styles.arrow, ...styles.leftArrow }}
            onClick={scrollLeft}
            aria-label="Scroll left"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>
        )}

        {/* Scrollable Products Container */}
        <div
          ref={scrollContainerRef}
          style={styles.productsContainer}
          onScroll={handleScroll}
        >
          {products.map((product, index) => (
            <ProductCard key={product.product_id || index} product={product} />
          ))}
        </div>

        {/* Right Arrow */}
        {showRightArrow && products.length > 3 && (
          <button
            style={{ ...styles.arrow, ...styles.rightArrow }}
            onClick={scrollRight}
            aria-label="Scroll right"
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        )}
      </div>

      {/* Product Summary (optional footer) */}
      <div style={styles.footer}>
        <span style={styles.footerText}>
          Scroll to see all products →
        </span>
      </div>
    </div>
  );
};

// Styles
const styles = {
  container: {
    width: '100%',
    backgroundColor: '#f8fafc',
    borderRadius: '16px',
    padding: '20px',
    marginBottom: '12px',
    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05)',
  },
  voiceResponse: {
    fontSize: '15px',
    lineHeight: '1.6',
    color: '#475569',
    marginBottom: '16px',
    padding: '12px 16px',
    backgroundColor: '#ffffff',
    borderRadius: '12px',
    borderLeft: '3px solid #3B82F6',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  },
  productCount: {
    fontSize: '16px',
    fontWeight: '600',
    color: '#1e293b',
  },
  carouselWrapper: {
    position: 'relative',
    width: '100%',
  },
  productsContainer: {
    display: 'flex',
    gap: '16px',
    overflowX: 'auto',
    scrollBehavior: 'smooth',
    paddingBottom: '8px',
    // Hide scrollbar but keep functionality
    scrollbarWidth: 'none', // Firefox
    msOverflowStyle: 'none', // IE/Edge
    WebkitOverflowScrolling: 'touch', // iOS smooth scrolling
  },
  arrow: {
    position: 'absolute',
    top: '50%',
    transform: 'translateY(-50%)',
    width: '40px',
    height: '40px',
    borderRadius: '50%',
    border: 'none',
    backgroundColor: '#ffffff',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    zIndex: 10,
    color: '#1e293b',
    transition: 'all 0.2s ease',
    ':hover': {
      backgroundColor: '#f8fafc',
      boxShadow: '0 4px 12px rgba(0, 0, 0, 0.2)',
    },
    ':active': {
      transform: 'translateY(-50%) scale(0.95)',
    },
  },
  leftArrow: {
    left: '-20px',
  },
  rightArrow: {
    right: '-20px',
  },
  footer: {
    marginTop: '12px',
    textAlign: 'center',
  },
  footerText: {
    fontSize: '13px',
    color: '#94a3b8',
    fontStyle: 'italic',
  },
};

// Add CSS to hide scrollbar
if (typeof document !== 'undefined') {
  const style = document.createElement('style');
  style.textContent = `
    /* Hide scrollbar for Chrome, Safari and Opera */
    .product-carousel-container::-webkit-scrollbar {
      display: none;
    }
  `;
  if (!document.querySelector('style[data-product-carousel-styles]')) {
    style.setAttribute('data-product-carousel-styles', '');
    document.head.appendChild(style);
  }
}

export default ProductCarousel;
