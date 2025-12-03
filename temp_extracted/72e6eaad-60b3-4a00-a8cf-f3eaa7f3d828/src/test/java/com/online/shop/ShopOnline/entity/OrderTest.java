package com.online.shop.ShopOnline.entity;

import com.online.shop.ShopOnline.entity.Order;
import com.online.shop.ShopOnline.entity.OrderController;
import com.online.shop.ShopOnline.entity.OrderService;
import java.util.*;
import java.util.ArrayList;
import java.util.Optional;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

Here is the complete JUnit 5 test class for the Order class:



@ExtendWith(MockitoExtension.class)
public class OrderTest {

    @InjectMocks
    private Order order;

    @Mock
    private Long id;

    @Mock
    private String productName;

    @Mock
    private Long productId;

    @Mock
    private Integer price;

    @Test
    public void testGetterSetter() {
        order.setId(id);
        order.setProductName(productName);
        order.setProductId(productId);
        order.setPrice(price);

        assert(order.getId().equals(id));
        assert(order.getProductName().equals(productName));
        assert(order.getProductId().equals(productId));
        assert(order.getPrice().equals(price));
    }

    @Test
    public void testNoArgsConstructor() {
        Order order = new Order();
        assert(order.getId() == null);
        assert(order.getProductName() == null);
        assert(order.getProductId() == null);
        assert(order.getPrice() == null);
    }

    @Test
    public void testAllArgsConstructor() {
        Order order = new Order(id, productName, productId, price);
        assert(order.getId().equals(id));
        assert(order.getProductName().equals(productName));
        assert(order.getProductId().equals(productId));
        assert(order.getPrice().equals(price));
    }
}